"""Migration permission is granted only inside the dedicated Runner slice."""

import os
import pwd
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from reverse_hr.shared.paths import REPOSITORY_ROOT

SCRIPT = REPOSITORY_ROOT / "scripts/delegate_runner_slice.py"


@pytest.mark.parametrize("leaf", [".control", "anchor", ""])
def test_permission_is_scoped_to_runner_slice(monkeypatch, leaf):
    base = "/reverse.slice/reverse-hr.slice/reverse-hr-runner.slice"
    group = base + "/reverse-hr-runner-scope.service" + ("/" + leaf if leaf else "")
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(Path, "read_text", lambda *_: "0::" + group)
    monkeypatch.setattr(pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=501, pw_gid=501))
    changed = []
    monkeypatch.setattr(os, "chown", lambda path, uid, gid: changed.append((str(path), uid, gid)))
    runpy.run_path(str(SCRIPT))
    assert changed == [
        (f"/sys/fs/cgroup{base}/{name}", 501, 501) for name in ("cgroup.procs", "cgroup.threads")
    ]


@pytest.mark.parametrize(
    "group",
    [
        "/system.slice/reverse-hr-runner-scope.service/.control",
        "/reverse-hr-runner.slice/other.service/.control",
        "/",
    ],
)
def test_unrelated_scope_never_receives_permission(monkeypatch, group):
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(Path, "read_text", lambda *_: "0::" + group)
    monkeypatch.setattr(os, "chown", lambda *_: pytest.fail("Permissions must remain unchanged"))
    with pytest.raises(SystemExit, match="Dedicated Runner slice required"):
        runpy.run_path(str(SCRIPT))
