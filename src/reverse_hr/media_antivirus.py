"""Bounded ClamD INSTREAM client; only a clean verdict with fresh signatures passes."""

import hashlib
import socket
import struct
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from reverse_hr.contracts import Contract


class AntivirusReport(Contract):
    engine: str = Field(max_length=100)
    signature_version: int = Field(strict=True, gt=0)
    signatures_at: datetime
    scanned_at: datetime
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    verdict: Literal["clean"] = "clean"


class ClamdScanner:
    def __init__(self, settings):
        self.host, self.port = settings.media_clamd_host, settings.media_clamd_port
        self.timeout = settings.media_antivirus_timeout_seconds
        self.max_age = timedelta(hours=settings.media_antivirus_max_signature_age_hours)

    def exchange(self, message, raw, deadline):
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError
            return value

        with socket.create_connection((self.host, self.port), timeout=remaining()) as stream:
            stream.settimeout(remaining())
            stream.sendall(message)
            if raw is not None:
                for start in range(0, len(raw), 65536):
                    part = raw[start : start + 65536]
                    stream.settimeout(remaining())
                    stream.sendall(struct.pack("!I", len(part)) + part)
                stream.sendall(b"\0\0\0\0")
            reply = bytearray()
            while len(reply) <= 1024:
                stream.settimeout(remaining())
                part = stream.recv(1025 - len(reply))
                if not part:
                    raise ValueError("Incomplete verdict")
                reply.extend(part)
                if reply.endswith(b"\0"):
                    return reply[:-1].decode("ascii")
            raise ValueError("Excessive verdict")

    def signatures(self, deadline):
        version = self.exchange(b"zVERSION\0", None, deadline)
        engine, number, timestamp = version.split("/", 2)
        if not engine.startswith("ClamAV ") or len(engine) > 100:
            raise ValueError("Invalid engine")
        signature_version = int(number)
        signatures_at = datetime.strptime(timestamp, "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC)
        if (
            signature_version <= 0
            or not -timedelta(minutes=5) <= datetime.now(UTC) - signatures_at <= self.max_age
        ):
            raise ValueError("Stale signatures")
        return engine, signature_version, signatures_at

    def ready(self):
        try:
            self.signatures(time.monotonic() + self.timeout)
        except (OSError, ValueError, OverflowError) as exc:
            raise HTTPException(503, "Antivirus unavailable or signatures stale") from exc

    def scan(self, raw):
        if not 1 <= len(raw) <= 32 * 1024 * 1024:
            raise HTTPException(422, "Invalid scan size")
        deadline = time.monotonic() + self.timeout
        try:
            engine, signature_version, signatures_at = self.signatures(deadline)
            verdict = self.exchange(b"zINSTREAM\0", raw, deadline)
        except (OSError, ValueError, OverflowError) as exc:
            raise HTTPException(503, "Antivirus unavailable or signatures stale") from exc
        if verdict != "stream: OK":
            if verdict.startswith("stream: ") and verdict.endswith(" FOUND"):
                raise HTTPException(422, "Recording rejected by antivirus")
            raise HTTPException(503, "Antivirus did not confirm a clean recording")
        return AntivirusReport(
            engine=engine,
            signature_version=signature_version,
            signatures_at=signatures_at,
            scanned_at=datetime.now(UTC),
            digest=hashlib.sha256(raw).hexdigest(),
        )
