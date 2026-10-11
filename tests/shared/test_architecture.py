"""Enforce source ownership so folder moves cannot hide service coupling."""

import ast

import pytest

from reverse_hr.platform.registry import service_app
from reverse_hr.platform.settings import SIGNING_SERVICES, Settings
from reverse_hr.shared.paths import PACKAGE_ROOT


def imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name


def test_shared_code_and_contracts_do_not_import_service_internals():
    violations = []
    for layer in ("shared", "contracts"):
        for path in (PACKAGE_ROOT / layer).rglob("*.py"):
            for line, module in imports(path):
                if module.startswith("reverse_hr.services."):
                    violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{line}: {module}")
    assert not violations, "\n".join(violations)


def test_services_do_not_import_another_services_implementation():
    violations = []
    for path in (PACKAGE_ROOT / "services").rglob("*.py"):
        owner = path.relative_to(PACKAGE_ROOT / "services").parts[0]
        for line, module in imports(path):
            if module.startswith("reverse_hr.services.") and module.split(".")[2] != owner:
                violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{line}: {module}")
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize("name", SIGNING_SERVICES)
def test_service_entry_point_rejects_a_different_service(name):
    other = "privacy" if name != "privacy" else "candidate"
    with pytest.raises(ValueError, match="does not match"):
        service_app(name).create_app(Settings(service_name=other))


def test_registry_does_not_import_service_implementations():
    path = PACKAGE_ROOT / "platform/registry.py"
    assert all(not module.startswith("reverse_hr.services.") for _, module in imports(path))
