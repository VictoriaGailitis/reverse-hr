"""A queue failure stops sibling workers; cleanup scope remains independently anchored."""

import subprocess
from pathlib import Path

import pytest

from reverse_hr.services.code_runner import runner_node


def test_one_failed_queue_stops_and_reaps_all_siblings(monkeypatch):
    handlers = {}
    monkeypatch.setattr(
        runner_node.signal, "signal", lambda sig, handler: handlers.setdefault(sig, handler)
    )
    children = []

    class Child:
        def __init__(self, args):
            self.args = args
            self.stopped = False
            children.append(self)

        def wait(self, timeout=None):
            if self.stopped:
                return -15
            if self.args[-1] == "validate":
                return 2
            raise subprocess.TimeoutExpired(self.args, timeout)

        def poll(self):
            return -15 if self.stopped else None

        def terminate(self):
            self.stopped = True

        def kill(self):
            self.stopped = True

    with pytest.raises(RuntimeError, match="queue exited"):
        runner_node.supervise(popen=Child)
    assert [p.args[-1] for p in children] == ["execute", "validate", "grade-tests"]
    assert all(p.stopped for p in children)


@pytest.mark.parametrize(
    "path",
    [
        "/system.slice/unrelated.service/anchor",
        "/system.slice/reverse-hr-runner-scope.service/worker",
        "/",
    ],
)
def test_scope_refuses_host_or_wrong_unit(monkeypatch, path):
    monkeypatch.setattr(Path, "read_text", lambda *_: "0::" + path)
    with pytest.raises(ValueError, match="scope anchor"):
        runner_node.delegated_parent()


def test_scope_enables_controllers_only_on_dedicated_empty_parent(monkeypatch):
    parent = (
        "/sys/fs/cgroup/reverse.slice/reverse-hr.slice/reverse-hr-runner.slice/"
        "reverse-hr-runner-scope.service"
    )
    writes = []

    def read(path):
        if str(path) == "/proc/self/cgroup":
            return "0::" + parent.removeprefix("/sys/fs/cgroup") + "/anchor"
        assert str(path) == parent + "/cgroup.controllers"
        return "cpu memory pids"

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(Path, "write_text", lambda path, value: writes.append((str(path), value)))
    assert runner_node.delegated_parent() == Path(parent)
    assert writes == [(parent + "/cgroup.subtree_control", "+cpu +memory +pids")]


def test_arm64_runtime_requires_matching_manifest(tmp_path, monkeypatch):
    from reverse_hr.services.code_runner import sandbox
    from tests.services.code_runner.test_sandbox import fixture_runtime

    config, root = fixture_runtime(tmp_path)
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox.platform, "machine", lambda: "aarch64")
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.NsjailExecutor(config).validate()
    manifest = Path(config.runner_rootfs_manifest)
    manifest.write_text(sandbox.inventory(root, architecture="aarch64").model_dump_json())
    config.runner_rootfs_manifest_sha256 = sandbox.digest(manifest)
    assert sandbox.NsjailExecutor(config).validate()[1] == root
    profile = sandbox.jail_config(root, tmp_path, tmp_path, "code")
    assert "runner_policy_aarch64.kafel" in profile and "DEFAULT ALLOW" not in profile
