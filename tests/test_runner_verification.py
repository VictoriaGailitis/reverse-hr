import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from reverse_hr.runner_readiness import ProbeRecord
from reverse_hr.settings import Settings


@pytest.mark.parametrize("result", ["pass", "failure", "skip", "partial", "changed", "exit"])
def test_probe_record_requires_entire_successful_unchanged_suite(tmp_path, monkeypatch, result):
    spec = importlib.util.spec_from_file_location("runner_verifier", "scripts/verify_runner.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    settings = Settings(service_name="code-runner", runner_node_id=uuid4())
    monkeypatch.setattr(verifier, "Settings", lambda: settings)
    monkeypatch.setattr(
        verifier,
        "fingerprint",
        Mock(side_effect=["a" * 64, "b" * 64] if result == "changed" else lambda _: "a" * 64),
    )
    output = tmp_path / "probes.json"
    old = ProbeRecord(
        node_id=settings.runner_node_id,
        checked_at=datetime.now(UTC),
        fingerprint="0" * 64,
        passed=12,
    )
    output.write_text(old.model_dump_json())
    output.chmod(0o600)
    monkeypatch.setattr(sys, "argv", ["verify_runner", "--output", str(output)])
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k select_one")
    monkeypatch.setenv("PYTEST_PLUGINS", "unexpected")
    observed = []

    def probes(args, *, env, timeout, check):
        assert env["HR_TEST_ENABLE_SANDBOX"] == "1"
        assert "PYTEST_ADDOPTS" not in env and "PYTEST_PLUGINS" not in env
        assert env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
        assert "addopts=" in args and not check and timeout == 180
        report = Path(next(a.split("=", 1)[1] for a in args if a.startswith("--junitxml=")))
        count = 11 if result == "partial" else 12
        error = "<failure/>" if result == "failure" else "<skipped/>" if result == "skip" else ""
        cases = f"<testcase>{error}</testcase>" + "<testcase/>" * (count - 1)
        report.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
        observed.append(args)
        return SimpleNamespace(returncode=1 if result == "exit" else 0)

    monkeypatch.setattr(verifier.subprocess, "run", probes)
    if result == "pass":
        verifier.main()
        record = ProbeRecord.model_validate_json(output.read_text())
        assert record.passed == 12 and record.fingerprint == "a" * 64
        assert output.stat().st_mode & 0o777 == 0o600
        assert record.node_id == settings.runner_node_id
    else:
        with pytest.raises(SystemExit) as error:
            verifier.main()
        assert error.value.code == 2 and not output.exists()
    assert len(observed) == 1


def test_verifier_refuses_replacing_arbitrary_existing_file(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("runner_verifier", "scripts/verify_runner.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    monkeypatch.setattr(
        verifier, "Settings", lambda: Settings(service_name="code-runner", runner_node_id=uuid4())
    )
    monkeypatch.setattr(verifier, "fingerprint", lambda _: "a" * 64)
    output = tmp_path / "existing.txt"
    output.write_text("retained user data")
    output.chmod(0o600)
    monkeypatch.setattr(sys, "argv", ["verify_runner", "--output", str(output)])
    mock = Mock()
    monkeypatch.setattr(verifier.subprocess, "run", mock)
    with pytest.raises(SystemExit):
        verifier.main()
    assert output.read_text() == "retained user data"
    mock.assert_not_called()
