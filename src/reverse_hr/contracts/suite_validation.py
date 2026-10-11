"""Guest inputs and bound host captures for suite validation; no executor admission.

This module neither executes code nor certifies captures. The future durable
validation worker must authenticate their provenance and confirm sandbox cleanup.
"""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.runner import Output
from reverse_hr.contracts.suite_pin import SuitePin as SuitePin
from reverse_hr.contracts.test_suites import SuiteDefinition, TestCase, digest, validate_captures
from reverse_hr.contracts.workspace import FilesCommand


class CaseInput(Contract):
    source_kind: Literal["reference", "mutant"]
    source_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    case_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    manifest: FilesCommand
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent(self):
        if digest(self.manifest) != self.manifest_digest:
            raise ValueError("Guest manifest digest mismatch")
        return self


class ValidationPlan(Contract):
    validation_id: UUID
    pin: SuitePin
    format: Literal["code", "sql"]
    runtime_contract: Literal["python-3.12-sqlite-demo-v1"]
    comparison_policy: Literal["utf8-exact-v1"]
    inputs: list[CaseInput] = Field(min_length=3, max_length=120)

    @model_validator(mode="after")
    def coherent(self):
        keys = [(item.source_kind, item.source_key, item.case_key) for item in self.inputs]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate planned execution")
        return self


class CaseCapture(Contract):
    validation_id: UUID
    pin: SuitePin
    attempt_id: UUID
    source_kind: Literal["reference", "mutant"]
    source_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    case_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    output: Output


def guest_input(source: FilesCommand, case: TestCase) -> FilesCommand:
    """Copy source plus inputs only; expected stdout/stderr remain on the host."""
    source = FilesCommand.model_validate(source.model_dump(mode="json"))
    case = TestCase.model_validate(case.model_dump(mode="json"))
    if any(
        file.path == "test_inputs" or file.path.startswith("test_inputs/") for file in source.files
    ):
        raise ValueError("Source cannot supply trusted test inputs")
    merged = FilesCommand(files=source.files + case.fixtures)
    paths = {file.path for file in merged.files}
    if any(path.startswith(other + "/") for path in paths for other in paths if path != other):
        raise ValueError("Source/fixture path collision")
    # Independent copy: editing projected files cannot mutate the suite.
    return FilesCommand(files=sorted(merged.files, key=lambda file: file.path)).model_copy(
        deep=True
    )


def build_plan(suite: SuiteDefinition, pin: SuitePin, validation_id: UUID) -> ValidationPlan:
    # Revalidate even in-process instances (model_copy/update is not validation).
    suite = SuiteDefinition.model_validate(suite.model_dump(mode="json"))
    pin = SuitePin.model_validate(pin.model_dump(mode="json"))
    if digest(suite) != pin.definition_digest:
        raise ValueError("Definition differs from pinned suite")
    inputs = []
    sources = [("reference", "reference", suite.reference)] + [
        ("mutant", item.key, item.source) for item in suite.mutants
    ]
    for kind, key, source in sources:
        for case in suite.cases:
            manifest = guest_input(source, case)
            inputs.append(
                CaseInput(
                    source_kind=kind,
                    source_key=key,
                    case_key=case.key,
                    manifest=manifest,
                    manifest_digest=digest(manifest),
                )
            )
    return ValidationPlan(
        validation_id=validation_id,
        pin=pin,
        format=suite.format,
        runtime_contract=suite.runtime_contract,
        comparison_policy=suite.comparison_policy,
        inputs=inputs,
    )


def compare_bound_captures(
    suite: SuiteDefinition, plan: ValidationPlan, captures: list[CaseCapture]
) -> Literal["accepted", "rejected", "inconclusive"]:
    """Binding/matrix check only; accepted is not proof of trusted execution."""
    try:
        plan = ValidationPlan.model_validate(plan.model_dump(mode="json"))
        expected = build_plan(suite, plan.pin, plan.validation_id)
        if plan != expected or len(captures) != len(plan.inputs):
            return "inconclusive"
        planned = {(item.source_kind, item.source_key, item.case_key): item for item in plan.inputs}
        seen, attempts = set(), set()
        reference, mutants = {}, {}
        for raw in captures:
            capture = CaseCapture.model_validate(raw.model_dump(mode="json"))
            key = (capture.source_kind, capture.source_key, capture.case_key)
            item = planned.get(key)
            if (
                item is None
                or key in seen
                or capture.attempt_id in attempts
                or capture.validation_id != plan.validation_id
                or capture.pin != plan.pin
                or capture.manifest_digest != item.manifest_digest
            ):
                return "inconclusive"
            seen.add(key)
            attempts.add(capture.attempt_id)
            if capture.source_kind == "reference":
                reference[capture.case_key] = capture.output
            else:
                mutants.setdefault(capture.source_key, {})[capture.case_key] = capture.output
        return validate_captures(suite, reference, mutants)
    except ValueError:
        return "inconclusive"
