"""Explicit operator command: run real isolated probes, then write a private local record."""

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from reverse_hr.runner_readiness import ProbeRecord, fingerprint, read_record
from reverse_hr.sandbox import NsjailExecutor
from reverse_hr.settings import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    if settings.service_name != "code-runner" or settings.runner_node_id is None:
        parser.error("Verification requires Code Runner and stable node identity")
    adapter = NsjailExecutor(settings)
    try:
        before = fingerprint(adapter)  # validates real platform/artifacts/private scratch
        output = args.output
        parent = output.parent
        if (
            not output.is_absolute()
            or parent.resolve() != parent
            or parent.stat().st_uid != os.getuid()
            or parent.stat().st_mode & 0o077
        ):
            raise ValueError("Private absolute output directory required")
        if output.exists() or output.is_symlink():
            read_record(output)  # refuse to replace arbitrary files or links
            output.unlink()  # failed re-verification must not leave old approval available
        with tempfile.TemporaryDirectory(prefix="hr-probes-") as directory:
            report = Path(directory) / "report.xml"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_sandbox_live.py",
                    "-q",
                    "-o",
                    "addopts=",
                    "-p",
                    "no:cacheprovider",
                    f"--junitxml={report}",
                ],
                env={k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
                | {
                    "HR_TEST_ENABLE_SANDBOX": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                },
                timeout=180,
                check=False,
            )
            suite = ET.parse(report).getroot()
            cases = list(suite.iter("testcase"))
            if (
                result.returncode
                or len(cases) != 12
                or any(
                    list(case.iter(tag))
                    for case in cases
                    for tag in ("skipped", "failure", "error")
                )
            ):
                raise ValueError("Probes did not all pass")
        if fingerprint(adapter) != before:
            raise ValueError("Runtime changed during probes")
        record = ProbeRecord(
            node_id=settings.runner_node_id,
            checked_at=datetime.now(UTC),
            fingerprint=before,
            passed=len(cases),
        )
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(record.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        print(f"runner_probe_record_written passed={len(cases)}")
    except Exception:
        parser.error("Verification failed; no current probe record was issued")


if __name__ == "__main__":
    main()
