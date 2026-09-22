# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Every module must import, and every internal import must resolve.

A syntax check does not catch a NameError at module level, and it does not
catch a function-local `from app.x import y` that names something which does
not exist. Both happened in this codebase: app/recovery_endpoints.py failed on
import, and POST /admin/seed/run imported a function that was never defined.
"""
import ast
import importlib
import pathlib

import pytest

from tests.conftest import REPO_ROOT

MODULES = sorted(
    str(p.relative_to(REPO_ROOT)).replace("/", ".")[:-3].replace(".__init__", "")
    for p in (REPO_ROOT / "app").rglob("*.py")
)


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name):
    importlib.import_module(module_name)


def test_internal_imports_resolve():
    """Check names imported from app.* inside functions, which imports miss."""
    unresolved = []
    for path in sorted((REPO_ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ImportFrom) and node.module):
                continue
            if not node.module.startswith("app."):
                continue
            module = importlib.import_module(node.module)
            for alias in node.names:
                if alias.name != "*" and not hasattr(module, alias.name):
                    rel = path.relative_to(REPO_ROOT)
                    unresolved.append(f"{rel}:{node.lineno} {node.module}.{alias.name}")
    assert not unresolved, "Unresolved imports:\n" + "\n".join(unresolved)
