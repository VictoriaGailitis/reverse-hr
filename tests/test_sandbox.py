import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from reverse_hr import sandbox
from reverse_hr.domains.coding_workspace import FilesCommand
from reverse_hr.sandbox import (
    CleanupUnconfirmed,
    Limits,
    NsjailExecutor,
    Outcome,
    SandboxUnavailable,
    capture,
    digest,
    inventory,
    jail_config,
)
from reverse_hr.sandbox_guest import sql_demo, statements
from reverse_hr.settings import Settings


def test_disabled_and_non_linux_do_not_spawn(monkeypatch):
    spawn = Mock()
    monkeypatch.setattr(sandbox.subprocess, "Popen", spawn)
    for backend, system, arch in (
        ("disabled", "linux", "x86_64"),
        ("nsjail", "darwin", "x86_64"),
        ("nsjail", "linux", "aarch64"),
    ):
        monkeypatch.setattr(sandbox.sys, "platform", system)
        monkeypatch.setattr(sandbox.platform, "machine", lambda arch=arch: arch)
        with pytest.raises(SandboxUnavailable):
            NsjailExecutor(Settings(runner_backend=backend)).execute(
                "code", {"files": [{"path": "main.py", "content": "synthetic"}]}
            )
    spawn.assert_not_called()


def test_fixed_limits_and_no_network_or_environment_in_config(tmp_path):
    config = jail_config(tmp_path / 'root"fs', tmp_path / "source", tmp_path / "groups", "code")
    for required in (
        "clone_newnet: true",
        "iface_no_lo: true",
        "keep_env: false",
        "keep_caps: false",
        "disable_no_new_privs: false",
        "mount_proc: false",
        "use_cgroupv2: true",
        "cgroup_pids_max: 1",
        "cgroup_mem_max: 134217728",
        "time_limit: 3",
        "rlimit_cpu: 2",
        "nr_inodes=128",
        "rw: false",
        "mandatory: true",
    ):
        assert required in config
    assert 'root\\"fs' in config
    assert "DATABASE" not in config and "AMQP" not in config and "signing.key" not in config
    policy = Path(sandbox.__file__).with_name("runner_policy.kafel").read_text()
    allowed = {s.strip() for s in policy.split("ALLOW {")[1].split("}")[0].split(",")}
    assert not allowed & {
        "socket",
        "connect",
        "clone",
        "clone3",
        "fork",
        "vfork",
        "mount",
        "ptrace",
        "bpf",
        "unshare",
        "setsid",
    }
    assert "DEFAULT KILL" in policy
    with pytest.raises(SandboxUnavailable):
        jail_config(tmp_path, tmp_path, tmp_path, "shell")
    with pytest.raises(ValidationError):
        Limits(memory_bytes=999999999)


def fixture_runtime(tmp_path):
    root = tmp_path / "rootfs"
    (root / "runner").mkdir(parents=True)
    (root / "runner/guest.py").write_bytes(
        Path(sandbox.__file__).with_name("sandbox_guest.py").read_bytes()
    )
    (root / "usr/local/bin").mkdir(parents=True)
    (root / "usr/local/bin/python3.12").write_text("synthetic executable; never launched")
    (root / "usr/local/bin/python3.12").chmod(0o555)
    binary = tmp_path / "nsjail"
    binary.write_text("synthetic jail; never launched")
    binary.chmod(0o555)
    manifest = tmp_path / "rootfs.json"
    manifest.write_text(inventory(root).model_dump_json())
    groups = tmp_path / "groups"
    groups.mkdir()
    (groups / "cgroup.controllers").write_text("cpu memory pids")
    (groups / "cgroup.kill").touch()
    return Settings(
        runner_backend="nsjail",
        runner_nsjail_binary=str(binary),
        runner_nsjail_sha256=digest(binary),
        runner_rootfs=str(root),
        runner_rootfs_manifest=str(manifest),
        runner_rootfs_manifest_sha256=digest(manifest),
        runner_cgroup_parent=str(groups),
        runner_scratch=str(tmp_path),
    ), root


@pytest.mark.parametrize("tamper", ["guest", "binary", "manifest", "controllers", "file_added"])
def test_artifact_pins_and_required_controllers(tmp_path, monkeypatch, tamper):
    config, root = fixture_runtime(tmp_path)
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox.platform, "machine", lambda: "x86_64")
    executor = NsjailExecutor(config)
    assert executor.validate()[1] == root
    if tamper == "guest":
        (root / "runner/guest.py").write_text("tampered")
    elif tamper == "binary":
        Path(config.runner_nsjail_binary).chmod(0o755)
        Path(config.runner_nsjail_binary).write_text("tampered")
    elif tamper == "manifest":
        config.runner_rootfs_manifest_sha256 = "0" * 64
    elif tamper == "controllers":
        (Path(config.runner_cgroup_parent) / "cgroup.controllers").write_text("cpu")
    else:
        (root / "new-file").touch()
    with pytest.raises(SandboxUnavailable):
        executor.validate()


def test_inventory_does_not_follow_links_or_accept_devices(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "outside").symlink_to("../secret")
    with pytest.raises(SandboxUnavailable):
        inventory(root)
    (root / "outside").unlink()
    (root / "inside").write_text("synthetic")
    (root / "alias").symlink_to("/inside")
    result = inventory(root)
    assert result.files["alias"].target == "/inside"
    os.mkfifo(root / "pipe")
    with pytest.raises(SandboxUnavailable):
        inventory(root)


def adapter_fixture(tmp_path, monkeypatch):
    config, root = fixture_runtime(tmp_path)
    executor = NsjailExecutor(config)
    monkeypatch.setattr(
        executor,
        "validate",
        lambda: (Path(config.runner_nsjail_binary), root, Path(config.runner_cgroup_parent)),
    )
    # Synthetic cgroup filesystem for command construction/cleanup contract only.
    real_mkdir = Path.mkdir

    def mkdir(path, *args, **kwargs):
        result = real_mkdir(path, *args, **kwargs)
        if path.parent == Path(config.runner_cgroup_parent):
            (path / "cgroup.kill").touch()
        return result

    monkeypatch.setattr(Path, "mkdir", mkdir)
    spawn = Mock(return_value=Mock())
    monkeypatch.setattr(sandbox.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        sandbox, "capture", lambda *_: Outcome("executed", stdout="synthetic", exit_code=0)
    )

    def clean(group):
        (group / "cgroup.kill").unlink()
        group.rmdir()

    monkeypatch.setattr(executor, "cleanup", clean)
    return executor, spawn


def test_private_readonly_source_and_cleanup_before_return(tmp_path, monkeypatch):
    executor, spawn = adapter_fixture(tmp_path, monkeypatch)

    def capture_fake(_):
        stage = next(tmp_path.glob("hr-jail-*"))
        assert stage.stat().st_mode & 0o777 == 0o700
        assert (stage / "workspace/main.py").stat().st_mode & 0o777 == 0o444
        assert (stage / "workspace/main.py").read_text() == "synthetic"
        return Outcome("executed", stdout="synthetic", exit_code=0)

    monkeypatch.setattr(sandbox, "capture", capture_fake)
    outcome = executor.execute(
        "code", FilesCommand(files=[{"path": "main.py", "content": "synthetic"}])
    )
    assert outcome.stdout == "synthetic"
    args, kwargs = spawn.call_args
    assert args[0][0] == executor.settings.runner_nsjail_binary and args[0][1] == "--config"
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    assert kwargs["close_fds"] is True and "shell" not in kwargs
    assert not list(tmp_path.glob("hr-jail-*"))


def test_unconfirmed_cleanup_withholds_success(tmp_path, monkeypatch):
    executor, _ = adapter_fixture(tmp_path, monkeypatch)

    def fail(*_):
        raise OSError("synthetic cleanup failure")

    monkeypatch.setattr(executor, "cleanup", fail)
    with pytest.raises(CleanupUnconfirmed):
        executor.execute("code", FilesCommand(files=[{"path": "main.py", "content": "synthetic"}]))
    assert list(tmp_path.glob("hr-jail-*"))


@pytest.mark.parametrize(
    "kind,paths",
    [
        ("code", ["other.py"]),
        ("shell", ["main.py"]),
        ("code", ["main.py", "a", "a/b"]),
        ("sql", ["main.py"]),
    ],
)
def test_invalid_entrypoint_or_prefix_collision_does_not_spawn(tmp_path, monkeypatch, kind, paths):
    executor, spawn = adapter_fixture(tmp_path, monkeypatch)
    with pytest.raises(SandboxUnavailable):
        executor.execute(
            kind, FilesCommand(files=[{"path": p, "content": "synthetic"} for p in paths])
        )
    spawn.assert_not_called()
    assert not list(tmp_path.glob("hr-jail-*"))


def control(source):
    # Trusted constant control programs; no candidate code or claimed jail verification.
    return subprocess.Popen(
        [sys.executable, "-I", "-c", source],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        env={},
    )


def test_bounded_dual_output_and_timeout():
    normal = capture(control("import sys; print('out'); print('err', file=sys.stderr)"))
    assert normal.status == "executed" and normal.stdout == "out\n" and normal.stderr == "err\n"
    flood = capture(control("import sys; sys.stderr.write('x'*1000000)"), output_bytes=1024)
    assert flood.reason == "output_limit" and len(flood.stderr.encode()) <= 1024
    timed = capture(control("import time; time.sleep(10)"), wall_seconds=0.1)
    assert timed.reason == "time_limit"
    failed = capture(control("raise SystemExit(255)"))
    assert failed.status == "technical_error" and not failed.stdout and not failed.stderr
    explicit_exit = capture(control("raise SystemExit(137)"))
    assert explicit_exit.status == "runtime_error"  # An exit code alone is not proof of a limit.


def test_sql_demo_quotes_and_row_limit(capsys):
    sql_demo("SELECT 'a;b' AS text; SELECT SUM(value) AS total FROM demo_items;")
    replies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert replies[0]["rows"] == [["a;b"]] and replies[1]["rows"] == [[60]]
    assert len(list(statements("SELECT 1; -- comment ;\nSELECT 2;"))) == 2
    with pytest.raises(ValueError, match="row_limit"):
        sql_demo(
            "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<200) "
            "SELECT x FROM n;"
        )
    with pytest.raises(ValueError, match="statement_limit"):
        sql_demo("SELECT 1;" * 21)


@pytest.mark.parametrize(
    "source",
    [
        "ATTACH DATABASE '/tmp/forbidden.db' AS other;",
        "PRAGMA journal_mode;",
        "SELECT load_extension('/tmp/evil');",
    ],
)
def test_sql_denies_files_and_extensions(source):
    with pytest.raises(sqlite3.DatabaseError):
        sql_demo(source)


def test_replacement_decoding_does_not_expand_output_limit():
    result = capture(
        control("import sys; sys.stdout.buffer.write(bytes([255])*100000)"), output_bytes=1024
    )
    assert result.reason == "output_limit"
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 1024
