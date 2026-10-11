"""Opt-in experimental Linux adapter, requiring separately provisioned isolation probes.

Execution is not connected to the service worker; the durable cleanup lifecycle
is prepared separately. No host interpreter fallback exists.
"""

import hashlib
import json
import os
import platform
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import Field

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.workspace import FilesCommand


class SandboxUnavailable(Exception):
    pass


class CleanupUnconfirmed(SandboxUnavailable):
    """Retain a cleanup obligation; never acknowledge deletion as complete."""


class Limits(Contract):
    wall_seconds: Literal[3] = 3
    cpu_seconds: Literal[2] = 2
    memory_bytes: Literal[134217728] = 134217728
    processes: Literal[1] = 1
    output_bytes: Literal[65536] = 65536
    tmp_bytes: Literal[8388608] = 8388608
    tmp_inodes: Literal[128] = 128


class RootEntry(Contract):
    kind: Literal["file", "symlink"]
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    target: str | None = None


class RootManifest(Contract):
    runtime: Literal["python-3.12-sqlite-demo-v1"]
    architecture: Literal["x86_64", "aarch64"] = "x86_64"
    files: dict[str, RootEntry] = Field(min_length=1, max_length=50000)


@dataclass(frozen=True)
class Outcome:
    status: Literal["executed", "runtime_error", "limit_exceeded", "technical_error"]
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    reason: str | None = None


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalized(value):
    path = PurePosixPath(value)
    return bool(
        value
        and value.isascii()
        and str(path) == value
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and not any(ord(c) < 32 for c in value)
    )


def inventory(root, *, architecture="x86_64"):
    """Do not follow rootfs symlinks into the host when calculating an inventory."""
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if not normalized(relative):
            raise SandboxUnavailable()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            target = os.readlink(path)
            # Resolve lexically as inside the jail, not against host '/'.
            parts = [] if target.startswith("/") else list(PurePosixPath(relative).parent.parts)
            for part in target.split("/"):
                if part == "..":
                    if not parts:
                        raise SandboxUnavailable()
                    parts.pop()
                elif part not in {"", "."}:
                    parts.append(part)
            result[relative] = RootEntry(kind="symlink", target=target)
        elif stat.S_ISREG(mode):
            result[relative] = RootEntry(kind="file", sha256=digest(path))
        elif not stat.S_ISDIR(mode):
            raise SandboxUnavailable()  # No devices, sockets or FIFOs.
    return RootManifest(
        runtime="python-3.12-sqlite-demo-v1", architecture=architecture, files=result
    )


def jail_config(rootfs, workspace, cgroup, kind):
    if kind not in {"code", "sql"}:
        raise SandboxUnavailable()
    q = json.dumps
    policy = Path(__file__).with_name(
        "runner_policy_aarch64.kafel" if platform.machine() == "aarch64" else "runner_policy.kafel"
    )
    return f'''name: "reverse-hr-demo"
mode: ONCE
hostname: "runner"
cwd: "/workspace"
time_limit: 3
max_cpus: 1
keep_env: false
keep_caps: false
disable_no_new_privs: false
mount_proc: false
clone_newnet: true
clone_newuser: true
clone_newns: true
clone_newpid: true
clone_newipc: true
clone_newuts: true
clone_newcgroup: true
iface_no_lo: true
log_file: "/dev/null"
rlimit_as: 192
rlimit_core: 0
rlimit_cpu: 2
rlimit_fsize: 1
rlimit_nofile: 32
rlimit_stack: 8
use_cgroupv2: true
cgroupv2_mount: {q(str(cgroup))}
cgroup_mem_max: 134217728
cgroup_mem_swap_max: 0
cgroup_pids_max: 1
cgroup_cpu_ms_per_sec: 1000
uidmap {{ inside_id: "1000" outside_id: "{os.getuid()}" count: 1 }}
gidmap {{ inside_id: "1000" outside_id: "{os.getgid()}" count: 1 }}
envar: "PATH=/usr/local/bin"
envar: "LANG=C.UTF-8"
envar: "HOME=/tmp"
seccomp_policy_file: {q(str(policy))}
mount {{
 src: {q(str(rootfs))} dst: "/" is_bind: true rw: false
 nosuid: true nodev: true mandatory: true
}}
mount {{
 src: {q(str(workspace))} dst: "/workspace" is_bind: true rw: false
 nosuid: true nodev: true noexec: true mandatory: true
}}
mount {{
 dst: "/tmp" fstype: "tmpfs" options: "size=8388608,nr_inodes=128,mode=1777"
 rw: true nosuid: true nodev: true noexec: true mandatory: true
}}
exec_bin {{
 path: "/usr/local/bin/python3.12" arg: "-I" arg: "-B"
 arg: "/runner/guest.py" arg: {q(kind)}
}}
'''


def terminate(process):
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


def capture(process, *, wall_seconds=5, output_bytes=65536, stop_check=None):
    """Drain both pipes concurrently, with a combined byte bound and a host watchdog."""
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + wall_seconds
    reason = None
    try:
        with selectors.DefaultSelector() as selector:
            for name in buffers:
                pipe = getattr(process, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while selector.get_map():
                if stop_check and (reason := stop_check()):
                    break
                if time.monotonic() >= deadline:
                    reason = "time_limit"
                    break
                for key, _ in selector.select(
                    timeout=min(0.1, max(0, deadline - time.monotonic()))
                ):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    available = output_bytes - sum(len(b) for b in buffers.values())
                    buffers[key.data].extend(chunk[:available])
                    if len(chunk) > available:
                        reason = "output_limit"
                        break
                if reason:
                    break
        if reason is None and stop_check:
            reason = stop_check()
        if reason:
            terminate(process)
        else:
            # A program may close both output pipes and keep running. Continue polling
            # cancellation and deadline instead of blocking in wait for the full timeout.
            while process.poll() is None:
                if stop_check and (reason := stop_check()):
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "time_limit"
                    break
                try:
                    process.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    pass
            if reason:
                terminate(process)
    finally:
        terminate(process)
        process.stdout.close()
        process.stderr.close()
    values = {}
    remaining = output_bytes
    for name, value in buffers.items():
        decoded = bytes(value).decode("utf-8", errors="replace")
        text = decoded.encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
        values[name] = text
        remaining -= len(text.encode("utf-8"))
    if reason in {"user_cancelled", "access_withdrawn"}:
        return Outcome("cancelled", reason=reason)
    if reason == "admission_unavailable":
        return Outcome("technical_error", reason=reason)
    if reason:
        return Outcome("limit_exceeded", **values, reason=reason)
    if process.returncode == 255 or process.returncode < 0:
        return Outcome("technical_error", reason="sandbox_failed")
    # Signals/user exits cannot be distinguished reliably here: do not call them a resource limit.
    return Outcome(
        "executed" if process.returncode == 0 else "runtime_error",
        **values,
        exit_code=process.returncode,
    )


class NsjailExecutor:
    def __init__(self, settings):
        self.settings = settings

    def validate(self):
        if (
            self.settings.runner_backend != "nsjail"
            or sys.platform != "linux"
            or platform.machine() not in {"x86_64", "aarch64"}
        ):
            raise SandboxUnavailable()
        binary = Path(self.settings.runner_nsjail_binary)
        rootfs = Path(self.settings.runner_rootfs)
        manifest = Path(self.settings.runner_rootfs_manifest)
        cgroups = Path(self.settings.runner_cgroup_parent)
        if (
            not all(path.is_absolute() for path in (binary, rootfs, manifest, cgroups))
            or rootfs == Path("/")
            or rootfs.resolve() != rootfs
            or binary.is_symlink()
            or not os.access(binary, os.X_OK)
            or digest(binary) != self.settings.runner_nsjail_sha256
            or manifest.stat().st_size > 16 * 1024 * 1024
            or digest(manifest) != self.settings.runner_rootfs_manifest_sha256
        ):
            raise SandboxUnavailable()
        approved = RootManifest.model_validate_json(manifest.read_bytes())
        if (
            approved.architecture != platform.machine()
            or inventory(rootfs, architecture=approved.architecture) != approved
        ):
            raise SandboxUnavailable()
        guest = rootfs / "runner/guest.py"
        executable = rootfs / "usr/local/bin/python3.12"
        if (
            guest.is_symlink()
            or digest(guest) != digest(Path(__file__).with_name("sandbox_guest.py"))
            or not executable.is_file()
            or executable.is_symlink()
            or not os.access(executable, os.X_OK)
        ):
            raise SandboxUnavailable()
        if (
            not {"cpu", "memory", "pids"}
            <= set((cgroups / "cgroup.controllers").read_text().split())
            or not (cgroups / "cgroup.kill").exists()
        ):
            raise SandboxUnavailable()
        return binary, rootfs, cgroups

    def attempt_paths(self, attempt_id):
        name = "hr-jail-" + str(UUID(str(attempt_id)))
        scratch = Path(self.settings.runner_scratch)
        groups = Path(self.settings.runner_cgroup_parent)
        for parent in (scratch, groups):
            if not parent.is_absolute() or parent.resolve() != parent or not parent.is_dir():
                raise SandboxUnavailable()
        info = scratch.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SandboxUnavailable()
        return scratch / name, groups / name

    def cleanup_scope(self):
        """Bind recovery to the same provisioned directories, not just a node label."""
        self.validate()
        self.attempt_paths(UUID(int=0))
        paths = [Path(self.settings.runner_scratch), Path(self.settings.runner_cgroup_parent)]
        parts = []
        for path in paths:
            if not path.is_absolute() or path.resolve() != path or not path.is_dir():
                raise SandboxUnavailable()
            info = path.stat()
            parts.append([str(path), info.st_dev, info.st_ino])
        return hashlib.sha256(json.dumps(parts).encode()).hexdigest()

    @contextmanager
    def attempt_guard(self, attempt_id):
        # Persistent lock inode prevents unlink/recreate ABA. Candidate cannot reach this file.
        import fcntl

        root, _ = self.attempt_paths(attempt_id)
        fd = os.open(str(root) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise SandboxUnavailable()
            os.fchmod(fd, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CleanupUnconfirmed() from exc
            yield
        finally:
            os.close(fd)

    def cleanup_attempt(self, attempt_id):
        """Caller must hold attempt_guard; absence is safe only after durable fencing."""
        root, group = self.attempt_paths(attempt_id)
        if root.is_symlink() or group.is_symlink():
            raise CleanupUnconfirmed()
        try:
            self.cleanup(group)
            if root.exists():
                shutil.rmtree(root)
        except Exception as exc:
            raise CleanupUnconfirmed() from exc

    def execute(self, kind, manifest, *, attempt_id=None, stop_check=None):
        try:
            binary, rootfs, cgroup_parent = self.validate()
            manifest = FilesCommand.model_validate(manifest)
            paths = {f.path for f in manifest.files}
            entrypoint = {"code": "main.py", "sql": "query.sql"}.get(kind)
            if entrypoint is None or entrypoint not in paths:
                raise SandboxUnavailable()
            if any(
                str(parent) in paths for path in paths for parent in PurePosixPath(path).parents
            ):
                raise SandboxUnavailable()
        except Exception as exc:
            raise SandboxUnavailable() from exc
        if attempt_id is None:
            root = Path(tempfile.mkdtemp(prefix="hr-jail-", dir=self.settings.runner_scratch))
            cgroup = cgroup_parent / root.name
        else:
            # Service callers must use runner_lifecycle.execution_scope before this call.
            root, cgroup = self.attempt_paths(attempt_id)
            if cgroup.exists() or cgroup.is_symlink():
                raise CleanupUnconfirmed()
            root.mkdir(mode=0o700)

        created = False
        try:
            cgroup.mkdir(mode=0o700)
            created = True
            if not (cgroup / "cgroup.kill").exists():
                raise SandboxUnavailable()
            workspace = root / "workspace"
            workspace.mkdir(mode=0o755)
            for file in manifest.files:
                path = workspace / file.path
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(file.content)
                path.chmod(0o444)
            config = root / "jail.cfg"
            config.write_text(jail_config(rootfs, workspace, cgroup, kind))
            config.chmod(0o600)
            if stop_check and (reason := stop_check()):
                return Outcome(
                    "cancelled"
                    if reason in {"user_cancelled", "access_withdrawn"}
                    else "technical_error",
                    reason=reason,
                )
            process = subprocess.Popen(
                [str(binary), "--config", str(config)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                start_new_session=True,
                cwd=root,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            )
            outcome = capture(process, stop_check=stop_check) if stop_check else capture(process)
        finally:
            try:
                if created:
                    self.cleanup(cgroup)
                shutil.rmtree(root)
            except Exception as exc:
                raise CleanupUnconfirmed() from exc
        return outcome

    @staticmethod
    def cleanup(cgroup):
        if not cgroup.exists():
            return
        (cgroup / "cgroup.kill").write_text("1")
        until = time.monotonic() + 2
        while "populated 1" in (cgroup / "cgroup.events").read_text():
            if time.monotonic() >= until:
                raise CleanupUnconfirmed()
            time.sleep(0.02)
        for child in sorted(cgroup.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        cgroup.rmdir()
