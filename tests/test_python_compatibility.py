# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Every source file must work on the oldest supported Python.

`requirements.txt` and the Dockerfile target Python 3.11. Developing on a newer
interpreter hides constructs that only the newer one accepts, and the failure
then appears in CI rather than locally.

PEP 701 is the case that occurred here: Python 3.12 allows a backslash inside
the expression part of an f-string, 3.11 does not. `ast.parse` does not catch
it either, because its `feature_version` parameter has no effect on f-string
parsing. The check below therefore looks for the construct directly.
"""
import re

import pytest

from tests.conftest import REPO_ROOT

MINIMUM_PYTHON = (3, 11)

SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}

PYTHON_FILES = sorted(
    p for p in REPO_ROOT.rglob("*.py")
    if not set(p.relative_to(REPO_ROOT).parts) & SKIP_DIRS
)

# An f-string literal, in any of its prefixes and quote styles.
F_STRING = re.compile(r"""(?:rf|fr|f)(['"]{3}|['"])(.*?)(?<!\\)\1""", re.S)
# The expression part between braces, excluding the {{ and }} escapes.
EXPRESSION = re.compile(r"\{([^{}]*)\}")


def test_there_are_files_to_check():
    """Guards against the list quietly becoming empty."""
    assert len(PYTHON_FILES) > 40


@pytest.mark.parametrize(
    "path", PYTHON_FILES,
    ids=[str(p.relative_to(REPO_ROOT)) for p in PYTHON_FILES],
)
def test_no_backslash_inside_an_f_string_expression(path):
    source = path.read_text(encoding="utf-8")
    offenders = []
    for match in F_STRING.finditer(source):
        for expression in EXPRESSION.findall(match.group(2)):
            if "\\" in expression:
                line = source.count("\n", 0, match.start()) + 1
                offenders.append(f"line {line}: {{{expression[:60]}}}")

    assert not offenders, (
        f"{path.relative_to(REPO_ROOT)} uses a backslash inside an f-string "
        f"expression, which Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} "
        f"rejects:\n  " + "\n  ".join(offenders)
    )
