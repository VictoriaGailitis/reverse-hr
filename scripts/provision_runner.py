"""Install a native Linux node from reviewed local NsJail and Python 3.12.

Run as the operator (root) inside the dedicated VM, never on the platform host.
Does not copy platform secrets, enable a service, or switch queue mode.
"""

import argparse
import hashlib
import os
import platform
import pwd
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from uuid import uuid4


def copy_runtime(root, guest):
    stdlib = Path(sysconfig.get_path("stdlib"))
    destination = root / "usr/local/lib/python3.12"
    shutil.copytree(
        stdlib,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__", "site-packages", "dist-packages", "sitecustomize.py"
        ),
        symlinks=False,
    )
    binary = root / "usr/local/bin/python3.12"
    binary.parent.mkdir(parents=True)
    shutil.copy2(Path(sys.executable).resolve(), binary)
    # ldd only inspects the operator's trusted interpreter and its standard extensions.
    sources = [Path(sys.executable).resolve(), *sorted(stdlib.rglob("*.so"))]
    for source in sources:
        result = subprocess.run(
            ["/usr/bin/ldd", str(source)],
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        )
        if "not found" in result.stdout:
            raise ValueError("Interpreter dependency unavailable")
        for name in re.findall(r"(/[^\s()]+)", result.stdout):
            library = Path(name)
            target = root / library.relative_to("/")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(library.resolve(), target)
    for name in ("runner", "workspace", "tmp"):
        (root / name).mkdir()
    shutil.copy2(guest, root / "runner/guest.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nsjail", type=Path, required=True)
    parser.add_argument("--nsjail-sha256", required=True)
    parser.add_argument("--user", choices=["runner"], default="runner")
    args = parser.parse_args()
    if (
        sys.platform != "linux"
        or platform.machine() not in {"x86_64", "aarch64"}
        or sys.version_info[:2] != (3, 12)
        or os.getuid() != 0
    ):
        parser.error("Dedicated native Linux AMD64/ARM64 operator with Python 3.12 required")
    owner = pwd.getpwnam(args.user)
    if owner.pw_uid == 0 or args.nsjail.is_symlink() or not os.access(args.nsjail, os.X_OK):
        parser.error("Non-root worker and regular reviewed NsJail required")
    if hashlib.file_digest(args.nsjail.open("rb"), "sha256").hexdigest() != args.nsjail_sha256:
        parser.error("NsJail digest mismatch")
    repo = Path(__file__).resolve().parents[1]
    target = Path("/opt/reverse-hr-runner")
    if target.exists() or target.is_symlink():
        parser.error("Existing deployment must be stopped and reviewed separately")
    target.mkdir(mode=0o755)
    for name in ("src", "tests", "scripts", "infra/runner"):
        shutil.copytree(
            repo / name,
            target / name,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv"),
        )
    for name in ("pyproject.toml", "uv.lock", "alembic.ini"):
        shutil.copy2(repo / name, target / name)
    subprocess.run([sys.executable, "-m", "venv", str(target / ".venv")], check=True)
    python = target / ".venv/bin/python"
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--require-hashes",
            "-r",
            str(target / "infra/runner/requirements.lock"),
        ],
        check=True,
    )
    (target / "bin").mkdir()
    shutil.copy2(args.nsjail, target / "bin/nsjail")
    rootfs = target / "rootfs"
    rootfs.mkdir()
    copy_runtime(rootfs, target / "src/reverse_hr/services/code_runner/sandbox_guest.py")
    env = os.environ | {"PYTHONPATH": str(target / "src")}
    manifest = target / "rootfs-manifest.json"
    subprocess.run(
        [
            str(python),
            str(target / "scripts/runner_inventory.py"),
            "--rootfs",
            str(rootfs),
            "--output",
            str(manifest),
            "--architecture",
            platform.machine(),
        ],
        check=True,
        env=env,
    )
    # Artifacts are operator-owned, immutable to the worker, and readable in its jail.
    for base, directories, files in os.walk(target):
        for name in directories:
            Path(base, name).chmod(0o755)
        for name in files:
            path = Path(base, name)
            if not path.is_symlink():
                path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
    state = Path("/var/lib/reverse-hr-runner")
    state.mkdir(mode=0o700, exist_ok=True)
    if state.is_symlink():
        parser.error("Private state cannot be a symlink")
    os.chown(state, owner.pw_uid, owner.pw_gid)
    state.chmod(0o700)
    scratch = state / "scratch"
    scratch.mkdir(mode=0o700, exist_ok=True)
    os.chown(scratch, owner.pw_uid, owner.pw_gid)
    node = state / "node-id"
    if node.exists():
        parser.error("Existing node state must not be reinitialized")
    node.write_text(str(uuid4()) + "\n")
    node.chmod(0o600)
    config = Path("/etc/reverse-hr-runner")
    config.mkdir(mode=0o700, exist_ok=True)
    settings = {
        "HR_SERVICE_NAME": "code-runner",
        "HR_RUNNER_EXECUTION_ENABLED": "true",
        "HR_RUNNER_BACKEND": "nsjail",
        "HR_RUNNER_NODE_ID": node.read_text().strip(),
        "HR_RUNNER_NSJAIL_BINARY": str(target / "bin/nsjail"),
        "HR_RUNNER_NSJAIL_SHA256": args.nsjail_sha256,
        "HR_RUNNER_ROOTFS": str(rootfs),
        "HR_RUNNER_ROOTFS_MANIFEST": str(manifest),
        "HR_RUNNER_ROOTFS_MANIFEST_SHA256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "HR_RUNNER_SCRATCH": str(scratch),
        "HR_RUNNER_VERIFICATION_FILE": str(state / "probes.json"),
    }
    (config / "node.env").write_text("".join(f"{k}={v}\n" for k, v in settings.items()))
    (config / "node.env").chmod(0o600)
    for name in (
        "reverse-hr-runner.service",
        "reverse-hr-runner-scope.service",
        "reverse-hr-runner.slice",
        "reverse-hr-runner-refresh.service",
        "reverse-hr-runner-refresh.timer",
    ):
        shutil.copy2(target / "infra/runner" / name, Path("/etc/systemd/system") / name)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    print("Runner artifacts installed. Run real probes before enabling the queue.")


if __name__ == "__main__":
    main()
