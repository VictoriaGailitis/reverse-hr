"""Disposable host PostgreSQL fallback; never use or stop an existing cluster."""

import logging
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import URL

logging.disable(logging.CRITICAL)
pg_ctl, initdb = shutil.which("pg_ctl"), shutil.which("initdb")
if not pg_ctl or not initdb:
    raise SystemExit("Host PostgreSQL tools unavailable; no installation attempted")
if shutil.disk_usage("/tmp").free < 128 * 1024**2:
    raise SystemExit("Insufficient free space for a disposable host PostgreSQL cluster")

root = Path(tempfile.mkdtemp(prefix="reverse-hr-pg-", dir="/tmp"))
data, sockets = root / "data", root / "socket"
sockets.mkdir(mode=0o700)
password_file = root / "bootstrap-password"
password_file.write_text(secrets.token_hex(32))
password_file.chmod(0o600)
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
exit_code = 1
clean = True
stage = "initialize"


def run(arguments, *, timeout=30):
    return subprocess.run(arguments, capture_output=True, check=False, timeout=timeout)


try:
    result = run(
        [
            initdb,
            "-D",
            str(data),
            "--username=bootstrap",
            "--encoding=UTF8",
            "--locale=C",
            "--auth-host=scram-sha-256",
            "--auth-local=trust",
            "--pwfile=" + str(password_file),
        ]
    )
    password_file.unlink()
    if result.returncode:
        raise RuntimeError("Initialization unavailable")
    stage = "start"
    options = shlex.join(
        [
            "-h",
            "127.0.0.1",
            "-p",
            str(port),
            "-k",
            str(sockets),
            "-c",
            "shared_buffers=16MB",
            "-c",
            "max_wal_size=128MB",
            "-c",
            "min_wal_size=32MB",
        ]
    )
    result = run(
        [
            pg_ctl,
            "-D",
            str(data),
            "-l",
            str(root / "server.log"),
            "-w",
            "-t",
            "15",
            "-o",
            options,
            "start",
        ]
    )
    if result.returncode:
        raise RuntimeError("Startup unavailable")
    stage = "roles"
    with psycopg.connect(
        host=str(sockets), port=port, user="bootstrap", dbname="postgres", autocommit=True
    ) as connection:
        version = connection.execute("SHOW server_version").fetchone()[0]
        for name in (
            "candidate",
            "privacy",
            "employer",
            "assessment",
            "coding_workspace",
            "code_runner",
        ):
            password = secrets.token_hex(32)
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(name), sql.Literal(password)
                )
            )
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(name), sql.Identifier(name)
                )
            )
            connection.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            url = URL.create(
                "postgresql+psycopg",
                username=name,
                password=password,
                host="127.0.0.1",
                port=port,
                database=name,
            ).render_as_string(hide_password=False)
            os.environ[f"HR_TEST_{name.upper()}_DATABASE_URL"] = url
            if name == "candidate":
                os.environ["HR_TEST_POSTGRES_URL"] = url
            elif name == "privacy":
                os.environ["HR_TEST_PRIVACY_POSTGRES_URL"] = url
    for name in tuple(os.environ):
        if name.startswith("HR_TEST_") and name.endswith("AMQP_URL"):
            os.environ.pop(name)
    os.environ["HR_TEST_ENABLE_HTTP"] = "1"
    print(
        f"Disposable host PostgreSQL {version}; broker tests skipped; credentials omitted",
        flush=True,
    )
    exit_code = pytest.main(["-q", "--tb=short"])
except Exception:
    print(
        f"Disposable host PostgreSQL checks unavailable at {stage}; sensitive diagnostics omitted",
        flush=True,
    )
finally:
    try:
        status = run([pg_ctl, "-D", str(data), "status"], timeout=10)
        if status.returncode == 0:
            stopped = run([pg_ctl, "-D", str(data), "-w", "-t", "15", "-m", "fast", "stop"])
            clean = stopped.returncode == 0
    except Exception:
        clean = False
    if clean:
        shutil.rmtree(root)
        print("Disposable cluster stopped and removed", flush=True)
    else:
        print(f"Disposable cluster preserved for recovery: {root}", flush=True)
        exit_code = 1
raise SystemExit(exit_code)
