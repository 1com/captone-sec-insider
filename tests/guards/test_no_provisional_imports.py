"""Look-ahead code in sentinel.provisional must never reach production modules (Principle I)."""

import ast

from conftest import REPO

SRC = REPO / "src" / "sentinel"
ALLOWED = {SRC / "cli.py"}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def test_no_production_module_imports_provisional():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path in ALLOWED or (SRC / "provisional") in path.parents:
            continue
        if any(name.startswith("sentinel.provisional") for name in _imports(path)):
            offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == []
