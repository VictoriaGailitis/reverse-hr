"""Bounded full decode. Production runs this code in the isolated decoder container."""

import json
import math
import os
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import suppress
from pathlib import Path

from fastapi import HTTPException
from pydantic import Field

from reverse_hr.contracts.core import Contract
from reverse_hr.shared.media_antivirus import AntivirusReport

_DECODER_SLOT = threading.BoundedSemaphore(1)


class MediaValidation(Contract):
    validator: str = "ffmpeg-full-decode-v1"
    antivirus: AntivirusReport | None = None
    duration_ms: int = Field(strict=True, ge=1, le=7200000)
    audio_codec: str
    sample_rate: int
    channels: int
    video_codec: str | None = None
    width: int | None = None
    height: int | None = None


def command(args, timeout, limit=65536):
    """Drain bounded output; kill the process group on timeout or excess output."""
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        )
    except OSError as exc:
        raise HTTPException(503, "Media decoder unavailable") from exc
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HTTPException(503, "Media decoder deadline exceeded")
                for key, _ in selector.select(min(remaining, 0.2)):
                    part = os.read(key.fileobj.fileno(), 4096)
                    if not part:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(part)
                    if len(output) > limit:
                        raise HTTPException(422, "Media decoder output limit exceeded")
            try:
                result = process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired as exc:
                raise HTTPException(503, "Media decoder deadline exceeded") from exc
            if result == 78:
                raise HTTPException(503, "Media decoder isolation unavailable")
            if result != 0:
                raise HTTPException(422, "Recording cannot be decoded")
        return bytes(output)
    finally:
        # A decoder may exit while a descendant still holds the pipe open.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        process.stdout.close()


class FFmpegValidator:
    def __init__(self, settings, *, filesystem_isolated=False):
        self.ffprobe = shutil.which(settings.media_ffprobe_binary)
        self.ffmpeg = shutil.which(settings.media_ffmpeg_binary)
        self.timeout = settings.media_validation_timeout_seconds
        self.filesystem_isolated = filesystem_isolated

    def invoke(self, args, timeout, source):
        if self.filesystem_isolated:
            args = [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "shared/decoder_guest.py"),
                str(source),
                *args,
            ]
        return command(args, timeout)

    def validate(self, raw, mime, format):
        if not _DECODER_SLOT.acquire(blocking=False):
            raise HTTPException(503, "Media decoder is busy")
        try:
            return self._validate(raw, mime, format)
        finally:
            _DECODER_SLOT.release()

    def _validate(self, raw, mime, format):
        if not self.ffprobe or not self.ffmpeg:
            raise HTTPException(503, "Media decoder unavailable")
        if format not in {"voice", "vcv"} or not 1 <= len(raw) <= 32 * 1024 * 1024:
            raise HTTPException(422)
        demuxer = {
            "audio/webm": "matroska",
            "video/webm": "matroska",
            "audio/ogg": "ogg",
            "video/mp4": "mov",
        }.get(mime)
        if demuxer is None:
            raise HTTPException(422)
        deadline = time.monotonic() + self.timeout
        with tempfile.TemporaryDirectory(prefix="hr-media-") as temporary:
            source = Path(temporary) / "recording"
            source.write_bytes(raw)
            flags = [
                "-v",
                "error",
                "-max_alloc",
                "33554432",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                demuxer,
                "-f",
                demuxer,
            ]
            result = self.invoke(
                [
                    self.ffprobe,
                    "-threads",
                    "1",
                    *flags,
                    "-show_entries",
                    "format=format_name,duration:stream=codec_type,codec_name,sample_rate,channels,width,height,avg_frame_rate",
                    "-of",
                    "json",
                    str(source),
                ],
                self.timeout,
                source,
            )
            try:
                metadata = json.loads(result)
                streams = metadata["streams"]
                audio = [s for s in streams if s.get("codec_type") == "audio"]
                video = [s for s in streams if s.get("codec_type") == "video"]
                if len(audio) != 1 or len(streams) != (1 if format == "voice" else 2):
                    raise ValueError("Invalid streams")
                if len(video) != (0 if format == "voice" else 1):
                    raise ValueError("Invalid video")
                a = audio[0]
                codec = a["codec_name"]
                allowed_audio = {"opus", "vorbis"} if mime != "video/mp4" else {"aac"}
                if codec not in allowed_audio:
                    raise ValueError("Invalid audio codec")
                sample_rate, channels = int(a["sample_rate"]), int(a["channels"])
                if not 8000 <= sample_rate <= 48000 or not 1 <= channels <= 2:
                    raise ValueError("Invalid audio parameters")
                v = video[0] if video else None
                if v:
                    allowed_video = {"vp8", "vp9"} if mime == "video/webm" else {"h264"}
                    num, den = v["avg_frame_rate"].split("/")
                    rate = int(num) / int(den) if int(den) else 0
                    if (
                        v["codec_name"] not in allowed_video
                        or not 0 <= rate <= 60
                        or not 1 <= int(v["width"]) <= 1920
                        or not 1 <= int(v["height"]) <= 1080
                    ):
                        raise ValueError("Invalid video parameters")
                declared = metadata.get("format", {}).get("duration")
                if declared is not None and not 0 < float(declared) <= 7200:
                    raise ValueError("Invalid container duration")
            except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
                raise HTTPException(422, "Unsupported recording streams") from exc
            decode = self.invoke(
                [
                    self.ffmpeg,
                    "-nostdin",
                    "-xerror",
                    "-err_detect",
                    "explode",
                    "-threads",
                    "1",
                    *flags,
                    "-i",
                    str(source),
                    "-map",
                    "0:a:0",
                    *(["-map", "0:v:0"] if v else []),
                    "-threads",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    "-c:v",
                    "rawvideo",
                    "-progress",
                    "pipe:1",
                    "-stats_period",
                    "10",
                    "-f",
                    "null",
                    "-",
                ],
                max(0.001, deadline - time.monotonic()),
                source,
            )
            progress = {}
            for line in decode.decode("ascii", errors="strict").splitlines():
                key, _, value = line.partition("=")
                progress[key] = value
            try:
                duration = math.ceil(int(progress["out_time_us"]) / 1000)
                if progress.get("progress") != "end" or not 0 < duration <= 7200000:
                    raise ValueError("Invalid decoded duration")
                if v and int(progress.get("frame", "0")) <= 0:
                    raise ValueError("Missing decoded video")
                if v and int(progress["frame"]) * 1000 / duration > 61:
                    raise ValueError("Excessive decoded frame rate")
            except (KeyError, ValueError) as exc:
                raise HTTPException(422, "Incomplete recording decode") from exc
            return MediaValidation(
                duration_ms=duration,
                audio_codec=codec,
                sample_rate=sample_rate,
                channels=channels,
                video_codec=v["codec_name"] if v else None,
                width=int(v["width"]) if v else None,
                height=int(v["height"]) if v else None,
            )
