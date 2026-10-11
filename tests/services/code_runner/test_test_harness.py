"""Synthetic captures verify binding only, never sandbox execution certification."""

import copy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from reverse_hr.contracts.runner import Output
from reverse_hr.contracts.suite_validation import (
    CaseCapture,
    SuitePin,
    build_plan,
    compare_bound_captures,
    guest_input,
)
from reverse_hr.contracts.test_suites import SuiteDefinition, digest
from tests.services.assessment.test_assessment_tests import SPEC


@pytest.fixture
def setup():
    spec = copy.deepcopy(SPEC)
    spec["cases"][0]["fixtures"] = [{"path": "test_inputs/value.txt", "content": "input"}]
    # Same mutant key as the reference is safe only when source_kind is bound.
    spec["mutants"][0]["key"] = "reference"
    spec["cases"].append(
        {
            "key": "two",
            "criterion_key": "shape",
            "fixtures": [{"path": "test_inputs/value.txt", "content": "different"}],
            "expected_stdout": "secret expected",
            "expected_stderr": "secret stderr",
        }
    )
    suite = SuiteDefinition.model_validate(spec)
    pin = SuitePin(
        suite_id=uuid4(),
        revision_id=uuid4(),
        content_digest="a" * 64,
        definition_digest=digest(suite),
        runtime_fingerprint="b" * 64,
    )
    plan = build_plan(suite, pin, uuid4())
    outputs = {case.key: case for case in suite.cases}
    captures = [
        CaseCapture(
            validation_id=plan.validation_id,
            pin=pin,
            attempt_id=uuid4(),
            source_kind=item.source_kind,
            source_key=item.source_key,
            case_key=item.case_key,
            manifest_digest=item.manifest_digest,
            output=Output(
                status="executed",
                exit_code=0,
                stdout=outputs[item.case_key].expected_stdout,
                stderr=outputs[item.case_key].expected_stderr,
            )
            if item.source_kind == "reference"
            else Output(status="runtime_error", exit_code=1),
        )
        for item in plan.inputs
    ]
    return suite, pin, plan, captures


def test_plan_contains_only_guest_inputs_and_independent_cases(setup):
    suite, pin, plan, captures = setup
    assert len(plan.inputs) == 6
    assert plan.pin == pin
    assert plan.inputs[0].manifest.files[-1].content == "input"
    assert plan.inputs[1].manifest.files[-1].content == "different"
    assert "expected_stdout" not in plan.model_dump_json()
    assert "expected_stderr" not in plan.model_dump_json()
    assert "secret expected" not in plan.model_dump_json()
    assert "secret stderr" not in plan.model_dump_json()
    assert build_plan(suite, pin, plan.validation_id) == plan
    assert compare_bound_captures(suite, plan, list(reversed(captures))) == "accepted"
    plan.inputs[0].manifest.files[0].content = "changed projected source"
    assert suite.reference.files[0].content == SPEC["reference"]["files"][0]["content"]
    assert compare_bound_captures(suite, plan, captures) == "inconclusive"


@pytest.mark.parametrize(
    "field",
    ["suite_id", "revision_id", "content_digest", "definition_digest", "runtime_fingerprint"],
)
def test_foreign_capture_pins_cannot_be_combined(setup, field):
    suite, _, plan, captures = setup
    replacement = uuid4() if field.endswith("_id") else "c" * 64
    captures[0] = captures[0].model_copy(
        update={"pin": captures[0].pin.model_copy(update={field: replacement})}
    )
    assert compare_bound_captures(suite, plan, captures) == "inconclusive"


@pytest.mark.parametrize(
    "change",
    [
        "validation",
        "manifest",
        "case",
        "kind",
        "source",
        "attempt",
        "duplicate",
        "missing",
        "extra",
        "output",
    ],
)
def test_capture_matrix_binding(setup, change):
    suite, _, plan, captures = setup
    capture = captures[0]
    updates = {
        "validation": {"validation_id": uuid4()},
        "manifest": {"manifest_digest": "f" * 64},
        "case": {"case_key": "unknown"},
        "kind": {"source_kind": "mutant"},
        "source": {"source_key": "unknown"},
        "attempt": {"attempt_id": captures[1].attempt_id},
        "output": {"output": Output(status="technical_error", reason="sandbox_failed")},
    }
    if change == "duplicate":
        captures[1] = capture
    elif change == "missing":
        captures.pop()
    elif change == "extra":
        captures.append(capture)
    else:
        captures[0] = capture.model_copy(update=updates[change])
    assert compare_bound_captures(suite, plan, captures) == "inconclusive"


@pytest.mark.parametrize("change", ["source", "fixture", "expected", "policy", "pin"])
def test_changed_definition_does_not_reuse_old_plan(setup, change):
    suite, pin, plan, captures = setup
    if change == "source":
        suite.reference.files[0].content = "changed reference"
    elif change == "fixture":
        suite.cases[0].fixtures[0].content = "changed input"
    elif change == "expected":
        suite.cases[0].expected_stdout = "changed answer"
    elif change == "policy":
        suite.comparison_policy = "unsafe-policy"
    else:
        pin.definition_digest = "f" * 64
    assert compare_bound_captures(suite, plan, captures) == "inconclusive"
    with pytest.raises(ValueError):
        build_plan(suite, pin, plan.validation_id)


@pytest.mark.parametrize("change", ["remove", "add", "reorder", "duplicate", "digest", "fixture"])
def test_plan_must_be_exactly_regenerated_from_definition(setup, change):
    suite, _, plan, captures = setup
    if change == "remove":
        plan.inputs.pop()
    elif change == "add":
        plan.inputs.append(plan.inputs[0])
    elif change == "reorder":
        plan.inputs.reverse()
    elif change == "duplicate":
        plan.inputs[1] = plan.inputs[0]
    elif change == "digest":
        plan.inputs[0].manifest_digest = "f" * 64
    else:
        plan.inputs[0].manifest.files[-1].content = "other fixture"
        plan.inputs[0].manifest_digest = digest(plan.inputs[0].manifest)
    assert compare_bound_captures(suite, plan, captures) == "inconclusive"


def test_reference_and_mutant_outputs_cannot_swap(setup):
    suite, _, plan, captures = setup
    assert compare_bound_captures(suite, plan, captures) == "accepted"
    captures[0].output, captures[2].output = captures[2].output, captures[0].output
    assert compare_bound_captures(suite, plan, captures) == "rejected"


def test_projection_rejects_collisions_even_without_suite_validator(setup):
    suite, _, _, _ = setup
    source = suite.reference.model_copy(deep=True)
    source.files[0].path = "test_inputs"
    with pytest.raises(ValueError):
        guest_input(source, suite.cases[0])
    source.files[0].path = "test_inputs/value.txt"
    with pytest.raises(ValueError):
        guest_input(source, suite.cases[0])


def test_invalid_capture_instances_are_revalidated(setup):
    suite, _, plan, captures = setup
    captures[0].output = captures[0].output.model_copy(update={"exit_code": True})
    assert compare_bound_captures(suite, plan, captures) == "inconclusive"
    with pytest.raises(ValidationError):
        SuitePin(
            suite_id=uuid4(),
            revision_id=uuid4(),
            content_digest="bad",
            definition_digest="a" * 64,
            runtime_fingerprint="b" * 64,
        )


@pytest.mark.parametrize(
    "path", ["../outside", "test_inputs/other.txt", "/absolute", "main.py/file"]
)
def test_projection_revalidates_mutated_source_paths(setup, path):
    suite, _, _, _ = setup
    source = suite.reference.model_copy(deep=True)
    if path == "main.py/file":
        extra = source.files[0].model_copy(update={"path": path})
        source.files.append(extra)
    else:
        source.files[0].path = path
    with pytest.raises(ValueError):
        guest_input(source, suite.cases[0])
