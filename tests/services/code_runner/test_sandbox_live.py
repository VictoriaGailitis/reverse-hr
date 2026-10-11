"""Explicit opt-in Linux probes; unit mocks never certify actual isolation."""

import os
import time
from pathlib import Path

import pytest

from reverse_hr.contracts.workspace import FilesCommand
from reverse_hr.platform.settings import Settings
from reverse_hr.services.code_runner.sandbox import NsjailExecutor

pytestmark = pytest.mark.skipif(
    os.getenv("HR_TEST_ENABLE_SANDBOX") != "1", reason="Dedicated Linux sandbox probes not enabled"
)


@pytest.fixture
def executor():
    adapter = NsjailExecutor(Settings())
    adapter.validate()  # Wrong artifact/architecture/cgroups is a failure, not a skipped probe.
    baseline = adapter.execute(
        "code", FilesCommand(files=[{"path": "main.py", "content": "print('baseline')"}])
    )
    assert baseline.status == "executed" and baseline.stdout == "baseline\n"
    return adapter


@pytest.mark.parametrize(
    "source,output",
    [
        ("import os; print(sorted(os.environ))", "['HOME', 'LANG', 'PATH']\n"),
        (
            "from pathlib import Path; print(Path('/app').exists(), Path('/proc/1').exists())",
            "False False\n",
        ),
    ],
)
def test_guest_environment_and_platform_files_absent(executor, source, output):
    result = executor.execute("code", FilesCommand(files=[{"path": "main.py", "content": source}]))
    assert result.status == "executed" and result.stdout == output


@pytest.mark.parametrize(
    "source",
    [
        "import socket; socket.socket()",
        "import os; os.fork()",
        "import threading; t=threading.Thread(target=lambda: None); t.start(); t.join()",
        "x=bytearray(300*1024*1024)",
        "with open('/tmp/large','wb') as f: f.write(b'x'*(2*1024*1024))",
    ],
)
def test_network_process_memory_file_probes(executor, source):
    result = executor.execute("code", FilesCommand(files=[{"path": "main.py", "content": source}]))
    assert result.status == "runtime_error", result.status


def test_deadline_output_bound_and_cleanup(executor):
    start = time.monotonic()
    result = executor.execute(
        "code", FilesCommand(files=[{"path": "main.py", "content": "while True: pass"}])
    )
    assert result.status in {"runtime_error", "limit_exceeded"}
    assert time.monotonic() - start < 8
    result = executor.execute(
        "code", FilesCommand(files=[{"path": "main.py", "content": "while True: print('x'*1024)"}])
    )
    assert result.status == "limit_exceeded" and result.reason == "output_limit"
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 65536
    # execute() raises rather than returning if cleanup cannot be confirmed.
    assert not list(Path(executor.settings.runner_cgroup_parent).glob("hr-jail-*"))


def test_isolated_sql_demo(executor):
    result = executor.execute(
        "sql",
        FilesCommand(
            files=[{"path": "query.sql", "content": "SELECT SUM(value) FROM demo_items;"}]
        ),
    )
    assert result.status == "executed" and "[[60]]" in result.stdout


@pytest.mark.parametrize("reason", ["user_cancelled", "access_withdrawn", "admission_unavailable"])
def test_live_stop_and_cleanup(executor, reason):
    started = None

    def check():
        nonlocal started
        if started is None:
            started = time.monotonic()
        return reason if time.monotonic() - started > 0.2 else None

    result = executor.execute(
        "code",
        FilesCommand(files=[{"path": "main.py", "content": "while True: pass"}]),
        stop_check=check,
    )
    assert result.reason == reason
    assert result.status == (
        "technical_error" if reason == "admission_unavailable" else "cancelled"
    )
    assert not result.stdout and not result.stderr
    assert not list(Path(executor.settings.runner_cgroup_parent).glob("hr-jail-*"))
