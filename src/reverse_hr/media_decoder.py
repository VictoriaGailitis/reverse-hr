"""Credential-free decoder service on a private Unix socket (no network listener)."""

import http.client
import json
import os
import socket
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from reverse_hr.media_validation import FFmpegValidator, MediaValidation
from reverse_hr.settings import Settings

_LIMIT = 32 * 1024 * 1024


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("decoder", timeout=timeout)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


class IsolatedDecoder:
    def __init__(self, settings):
        self.path = settings.media_decoder_socket
        self.timeout = settings.media_validation_timeout_seconds + 2

    def ready(self):
        connection = UnixConnection(self.path, self.timeout)
        try:
            connection.request("GET", "/ready")
            response = connection.getresponse()
            raw = response.read(1025)
            if response.status != 200 or len(raw) > 1024 or json.loads(raw) != {"ready": True}:
                raise ValueError
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise HTTPException(503, "Isolated decoder unavailable") from exc
        finally:
            connection.close()

    def validate(self, raw, mime, format):
        if not self.path or not Path(self.path).is_absolute():
            raise HTTPException(503, "Isolated decoder is not configured")
        if (
            mime not in {"audio/webm", "audio/ogg", "video/webm", "video/mp4"}
            or format not in {"voice", "vcv"}
            or not 1 <= len(raw) <= _LIMIT
        ):
            raise HTTPException(422)
        connection = UnixConnection(self.path, self.timeout)
        try:
            connection.request(
                "POST",
                "/validate",
                body=raw,
                headers={"Content-Type": mime, "X-Recording-Format": format},
            )
            response = connection.getresponse()
            body = response.read(65537)
            if response.status == 422:
                raise HTTPException(422, "Recording cannot be decoded")
            if response.status != 200 or len(body) > 65536:
                raise HTTPException(503, "Isolated decoder unavailable")
            result = MediaValidation.model_validate(json.loads(body))
            if result.validator != "ffmpeg-isolated-container-v1" or result.antivirus is not None:
                raise ValueError("Invalid decoder receipt")
            return result
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise HTTPException(503, "Isolated decoder unavailable") from exc
        finally:
            connection.close()


def require_isolation():
    try:
        from reverse_hr.decoder_guest import abi

        abi()
        if sys.platform != "linux" or os.getuid() == 0 or not os.statvfs("/").f_flag & os.ST_RDONLY:
            raise ValueError
        status = dict(
            line.split(":", 1)
            for line in Path("/proc/self/status").read_text().splitlines()
            if ":" in line
        )
        if (
            any(int(status[key].strip(), 16) for key in ("CapEff", "CapPrm", "CapBnd"))
            or status["NoNewPrivs"].strip() != "1"
            or status["Seccomp"].strip() != "2"
        ):
            raise ValueError
        interfaces = [
            line.split(":", 1)[0].strip()
            for line in Path("/proc/net/dev").read_text().splitlines()
            if ":" in line
        ]
        if set(interfaces) != {"lo"}:
            raise ValueError
        cgroup = Path("/sys/fs/cgroup")
        if (
            not 1 <= int((cgroup / "pids.max").read_text()) <= 64
            or not 1 <= int((cgroup / "memory.max").read_text()) <= 512 * 1024 * 1024
        ):
            raise ValueError
        quota, period = (cgroup / "cpu.max").read_text().split()
        if not 0 < int(quota) <= int(period):
            raise ValueError
        if any(
            key.startswith("HR_") and key != "HR_MEDIA_VALIDATION_TIMEOUT_SECONDS"
            for key in os.environ
        ):
            raise ValueError
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Decoder container isolation is not established") from exc


def create_app(settings=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    settings = settings or Settings()
    decoder = FFmpegValidator(settings, filesystem_isolated=settings.decoder_container_required)
    slot = threading.BoundedSemaphore(1)

    @app.get("/ready")
    def ready():
        if settings.decoder_container_required:
            require_isolation()
        if settings.decoder_container_required and (
            decoder.ffmpeg != "/usr/bin/ffmpeg" or decoder.ffprobe != "/usr/bin/ffprobe"
        ):
            raise HTTPException(503)
        if not decoder.ffmpeg or not decoder.ffprobe:
            raise HTTPException(503)
        return {"ready": True}

    @app.post("/validate", response_model=MediaValidation)
    async def validate(request: Request):
        if settings.decoder_container_required:
            require_isolation()
        # Acquire before reading: concurrent uploads cannot multiply buffered payloads.
        if not slot.acquire(blocking=False):
            raise HTTPException(503)
        try:
            mime = request.headers.get("content-type", "")
            format = request.headers.get("x-recording-format", "")
            if mime not in {"audio/webm", "audio/ogg", "video/webm", "video/mp4"} or format not in {
                "voice",
                "vcv",
            }:
                raise HTTPException(422)
            raw = bytearray()
            async for part in request.stream():
                if len(raw) + len(part) > _LIMIT:
                    raise HTTPException(413)
                raw.extend(part)
            # Offload so the event loop can reject concurrent requests and serve readiness.
            from starlette.concurrency import run_in_threadpool

            report = await run_in_threadpool(decoder.validate, bytes(raw), mime, format)
            return report.model_copy(update={"validator": "ffmpeg-isolated-container-v1"})
        finally:
            slot.release()

    return app
