"""Local probe record gate; this is evidence of listed checks, not an escape certificate."""

import hashlib
import importlib.metadata
import json
import os
import platform
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from pydantic import Field

from reverse_hr.contracts import Contract
from reverse_hr.sandbox import SandboxUnavailable


class ProbeRecord(Contract):
    version: int = Field(default=1, ge=1, le=1, strict=True)
    node_id: UUID
    checked_at: datetime
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    passed: int = Field(ge=12, le=12, strict=True)


def fingerprint(executor):
    settings = executor.settings
    scope = executor.cleanup_scope()
    repo = Path(__file__).resolve().parents[2]
    paths = sorted((repo / "src/reverse_hr").rglob("*.py"))
    paths += sorted((repo / "migrations/domains/code-runner").glob("*.py"))
    paths += [
        repo / "src/reverse_hr/runner_policy.kafel",
        repo / "tests/test_sandbox_live.py",
        repo / "tests/conftest.py",
        repo / "scripts/verify_runner.py",
        repo / "pyproject.toml",
        repo / "uv.lock",
    ]
    sources = {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    data = {
        "node_id": str(settings.runner_node_id),
        "scope": scope,
        "binary": settings.runner_nsjail_sha256,
        "rootfs": settings.runner_rootfs_manifest_sha256,
        "python": sys.version,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in (
                "fastapi",
                "sqlalchemy",
                "pydantic",
                "pydantic-settings",
                "cryptography",
                "pyjwt",
            )
        },
        "kernel": platform.release(),
        "machine": platform.machine(),
        "sources": sources,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def read_record(path):
    path = Path(path)
    if not path.is_absolute() or path.parent.resolve() != path.parent:
        raise SandboxUnavailable()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > 32768
            or info.st_nlink != 1
        ):
            raise SandboxUnavailable()
        return ProbeRecord.model_validate_json(stream.read(32769))


def require_execution_ready(executor):
    settings = executor.settings
    try:
        if (
            settings.service_name != "code-runner"
            or not settings.runner_execution_enabled
            or settings.runner_node_id is None
            or not settings.runner_verification_file
        ):
            raise SandboxUnavailable()
        record = read_record(settings.runner_verification_file)
        now = datetime.now(UTC)
        if (
            record.checked_at.tzinfo is None
            or record.checked_at > now
            or record.checked_at < now - timedelta(hours=24)
            or record.node_id != settings.runner_node_id
            or record.fingerprint != fingerprint(executor)
        ):
            raise SandboxUnavailable()
    except Exception as exc:
        raise SandboxUnavailable() from exc
