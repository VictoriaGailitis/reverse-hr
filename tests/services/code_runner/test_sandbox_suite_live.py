"""Opt-in real NsJail executions for a pinned synthetic hidden test suite."""

import os
from uuid import uuid4

import pytest

from reverse_hr.contracts.runner import Output
from reverse_hr.contracts.suite_validation import (
    CaseCapture,
    SuitePin,
    build_plan,
    compare_bound_captures,
)
from reverse_hr.contracts.test_suites import SuiteDefinition, digest
from reverse_hr.platform.settings import Settings
from reverse_hr.services.code_runner.runner_readiness import read_record, require_execution_ready
from reverse_hr.services.code_runner.sandbox import NsjailExecutor

pytestmark = pytest.mark.skipif(
    os.getenv("HR_TEST_ENABLE_SANDBOX") != "1", reason="Dedicated Linux sandbox required"
)


def test_pinned_suite_executes_reference_and_rejects_both_mutants():
    executor = NsjailExecutor(Settings())
    require_execution_ready(executor)
    record = read_record(executor.settings.runner_verification_file)

    def source(expression):
        return {
            "files": [
                {
                    "path": "main.py",
                    "content": "from pathlib import Path\n"
                    "x=int(Path('test_inputs/value.txt').read_text())\n"
                    f"print({expression})\n",
                }
            ]
        }

    suite = SuiteDefinition.model_validate(
        {
            "format": "code",
            "runtime_contract": "python-3.12-sqlite-demo-v1",
            "comparison_policy": "utf8-exact-v1",
            "reference": source("x*2"),
            "mutants": [
                {
                    "key": name,
                    "description": "Synthetic wrong algorithm",
                    "source": source(expression),
                }
                for name, expression in [("addition", "x+1"), ("triple", "x*3")]
            ],
            "cases": [
                {
                    "key": f"case_{value}",
                    "criterion_key": "arithmetic",
                    "fixtures": [{"path": "test_inputs/value.txt", "content": str(value)}],
                    "expected_stdout": f"{value * 2}\n",
                }
                for value in (3, 8)
            ],
        }
    )
    pin = SuitePin(
        suite_id=uuid4(),
        revision_id=uuid4(),
        content_digest="a" * 64,
        definition_digest=digest(suite),
        runtime_fingerprint=record.fingerprint,
    )
    plan = build_plan(suite, pin, uuid4())
    assert "expected_stdout" not in plan.model_dump_json()
    captures = []
    for item in plan.inputs:
        result = executor.execute(plan.format, item.manifest)
        assert result.status == "executed", result
        captures.append(
            CaseCapture(
                validation_id=plan.validation_id,
                pin=pin,
                attempt_id=uuid4(),
                source_kind=item.source_kind,
                source_key=item.source_key,
                case_key=item.case_key,
                manifest_digest=item.manifest_digest,
                output=Output(
                    status=result.status,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.exit_code,
                    reason=result.reason,
                ),
            )
        )
    assert len(captures) == 6
    assert compare_bound_captures(suite, plan, captures) == "accepted"
