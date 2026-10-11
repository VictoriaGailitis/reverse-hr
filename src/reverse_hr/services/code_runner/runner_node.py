"""One delegated Linux node: real probes followed by all three Runner queues."""

import argparse
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from reverse_hr.platform.settings import Settings
from reverse_hr.services.code_runner.runner_readiness import require_execution_ready
from reverse_hr.services.code_runner.sandbox import NsjailExecutor

MODES = ("execute", "validate", "grade-tests")
SCOPE_FILE = Path("/var/lib/reverse-hr-runner/scope.json")


def delegated_parent():
    rows = Path("/proc/self/cgroup").read_text().splitlines()
    entries = [row[3:] for row in rows if row.startswith("0::")]
    if len(entries) != 1:
        raise ValueError("Unified delegated cgroup required")
    subgroup = Path("/sys/fs/cgroup") / entries[0].lstrip("/")
    if (
        subgroup.name != "anchor"
        or subgroup.parent.name != "reverse-hr-runner-scope.service"
        or subgroup.parent.parent.name != "reverse-hr-runner.slice"
    ):
        raise ValueError("Dedicated scope anchor and DelegateSubgroup=anchor required")
    parent = subgroup.parent
    if not {"cpu", "memory", "pids"} <= set((parent / "cgroup.controllers").read_text().split()):
        raise ValueError("Required controllers unavailable")
    (parent / "cgroup.subtree_control").write_text("+cpu +memory +pids")
    return parent


def hold_scope():
    parent = delegated_parent()
    info = parent.stat()
    data = {"path": str(parent), "device": info.st_dev, "inode": info.st_ino}
    if SCOPE_FILE.is_symlink():
        raise ValueError("Scope file cannot be a symlink")
    fd, name = tempfile.mkstemp(dir=SCOPE_FILE.parent, prefix="scope-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, SCOPE_FILE)
    finally:
        if Path(name).exists():
            Path(name).unlink()
    address = os.environ["NOTIFY_SOCKET"]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
        notify.connect("\0" + address[1:] if address.startswith("@") else address)
        notify.send(b"READY=1")
    # Keep the delegated parent and its inode stable across queue restarts/refreshes.
    while True:
        signal.pause()


def read_scope():
    fd = os.open(SCOPE_FILE, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_size > 4096
            or info.st_nlink != 1
        ):
            raise ValueError("Private worker-owned scope file required")
        data = json.loads(stream.read(4096))
    parent = Path(data["path"])
    if (
        not parent.is_absolute()
        or parent.resolve() != parent
        or parent.name != "reverse-hr-runner-scope.service"
        or parent.parent.name != "reverse-hr-runner.slice"
    ):
        raise ValueError("Dedicated delegated scope required")
    info = parent.stat()
    if (info.st_dev, info.st_ino) != (data["device"], data["inode"]):
        raise ValueError("Scope anchor changed")
    return parent


def supervise(*, popen=subprocess.Popen):
    processes = []
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    old_handlers = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        for mode in MODES:
            if stopped:
                break
            processes.append(popen([sys.executable, "-m", "reverse_hr.platform.worker", mode]))
        while not stopped:
            # A failed queue stops the whole node; systemd reruns probes before restart.
            for process in processes:
                try:
                    code = process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    continue
                raise RuntimeError(f"Runner queue exited ({code})")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for s, handler in old_handlers.items():
            signal.signal(s, handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--hold-scope", action="store_true")
    args = parser.parse_args()
    try:
        if args.hold_scope:
            hold_scope()
            return
        parent = read_scope()
        configured = os.environ.get("HR_RUNNER_CGROUP_PARENT")
        if configured and Path(configured) != parent:
            raise ValueError("Configured cleanup scope differs from delegation")
        os.environ["HR_RUNNER_CGROUP_PARENT"] = str(parent)
        settings = Settings()
        if settings.service_name != "code-runner" or not settings.runner_verification_file:
            raise ValueError("Code Runner configuration required")
        repo = Path(__file__).resolve().parents[4]
        subprocess.run(
            [
                sys.executable,
                str(repo / "scripts/verify_runner.py"),
                "--output",
                settings.runner_verification_file,
            ],
            cwd=repo,
            check=True,
        )
        require_execution_ready(NsjailExecutor(settings))
        if not args.verify_only:
            for key in (
                "HR_DATABASE_URL",
                "HR_EVENT_PRIVATE_KEY_FILE",
                "HR_EVENT_PUBLIC_KEYS_FILE",
                "HR_PRIVACY_API_URL",
                "HR_ASSESSMENT_API_URL",
                "HR_WORKSPACE_API_URL",
                "HR_EVALUATION_API_URL",
            ):
                if not os.environ.get(key):
                    raise ValueError("Explicit platform connection required")
            supervise()
    except Exception:
        # Exceptions may contain DB URLs or API credentials: keep service logs bounded.
        parser.error("Runner node failed readiness, probes or queue supervision")


if __name__ == "__main__":
    main()
