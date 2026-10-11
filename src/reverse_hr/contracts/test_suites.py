"""Bounded demo test specifications and host-side comparison; no code execution."""

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.runner import Output
from reverse_hr.contracts.workspace import File, FilesCommand
from reverse_hr.shared.signing import canonical

Key = str
Verdict = Literal["passed", "failed", "inconclusive"]


def digest(value: Contract) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def paths_valid(files: list[File]) -> bool:
    paths = {file.path for file in files}
    return len(paths) == len(files) and not any(
        path.startswith(other + "/") for path in paths for other in paths if path != other
    )


class TestCase(Contract):
    key: Key = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    criterion_key: Key = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    fixtures: list[File] = Field(default_factory=list, max_length=19)
    expected_stdout: str = Field(max_length=16384)
    expected_stderr: str = Field(default="", max_length=16384)

    @model_validator(mode="after")
    def bounded(self):
        if not paths_valid(self.fixtures) or any(
            not file.path.startswith("test_inputs/") for file in self.fixtures
        ):
            raise ValueError("Fixtures require distinct non-overlapping test_inputs paths")
        if sum(len(file.content.encode("utf-8")) for file in self.fixtures) > 131072:
            raise ValueError("Fixtures exceed input budget")
        if any(
            len(text.encode("utf-8")) > 16384
            for text in (self.expected_stdout, self.expected_stderr)
        ):
            raise ValueError("Expected output exceeds UTF-8 budget")
        return self


class Mutant(Contract):
    key: Key = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    source: FilesCommand


class SuiteDefinition(Contract):
    format: Literal["code", "sql"]
    runtime_contract: Literal["python-3.12-sqlite-demo-v1"]
    comparison_policy: Literal["utf8-exact-v1"]
    cases: list[TestCase] = Field(min_length=1, max_length=20)
    reference: FilesCommand
    mutants: list[Mutant] = Field(min_length=2, max_length=5)

    @model_validator(mode="after")
    def coherent(self):
        if len({case.key for case in self.cases}) != len(self.cases):
            raise ValueError("Case keys must be unique")
        if len({mutant.key for mutant in self.mutants}) != len(self.mutants):
            raise ValueError("Mutant keys must be unique")
        entry = "main.py" if self.format == "code" else "query.sql"
        sources = [self.reference, *(mutant.source for mutant in self.mutants)]
        for source in sources:
            if not paths_valid(source.files) or entry not in {file.path for file in source.files}:
                raise ValueError("Sources require entrypoint and non-overlapping paths")
            if any(
                file.path == "test_inputs" or file.path.startswith("test_inputs/")
                for file in source.files
            ):
                raise ValueError("Source cannot overwrite trusted test inputs")
            if any(len(source.files) + len(case.fixtures) > 20 for case in self.cases):
                raise ValueError("Merged source and fixtures exceed file budget")
            if any(
                sum(len(file.content.encode("utf-8")) for file in source.files + case.fixtures)
                > 262144
                for case in self.cases
            ):
                raise ValueError("Merged source and fixtures exceed snapshot budget")
        # File order is not a distinct solution.
        fingerprints = {
            hashlib.sha256(
                canonical(FilesCommand(files=sorted(source.files, key=lambda file: file.path)))
            ).hexdigest()
            for source in sources
        }
        if len(fingerprints) != len(sources):
            raise ValueError("Reference and mutant sources must be distinct")
        if len(canonical(self)) > 2097152:
            raise ValueError("Suite exceeds bounded size")
        return self


def compare(case: TestCase, output: Output) -> Verdict:
    """Call only with trusted host captures; stdout cannot attest to test success."""
    if output.status in {"technical_error", "cancelled", "limit_exceeded"}:
        # This first policy has no grading budget for execution limits.
        return "inconclusive"
    if output.status == "runtime_error":
        return "failed"
    return (
        "passed"
        if output.stdout == case.expected_stdout and output.stderr == case.expected_stderr
        else "failed"
    )


def validate_captures(
    suite: SuiteDefinition, reference: dict[str, Output], mutants: dict[str, dict[str, Output]]
) -> Literal["accepted", "rejected", "inconclusive"]:
    """Pure comparison of a complete matrix, never a runtime validation certificate."""
    keys = {case.key for case in suite.cases}
    if (
        set(reference) != keys
        or set(mutants) != {mutant.key for mutant in suite.mutants}
        or any(set(outputs) != keys for outputs in mutants.values())
    ):
        return "inconclusive"
    ref = [compare(case, reference[case.key]) for case in suite.cases]
    matrix = [
        [compare(case, outputs[case.key]) for case in suite.cases] for outputs in mutants.values()
    ]
    if "inconclusive" in ref or any("inconclusive" in row for row in matrix):
        return "inconclusive"
    if any(item != "passed" for item in ref) or any("failed" not in row for row in matrix):
        return "rejected"
    return "accepted"
