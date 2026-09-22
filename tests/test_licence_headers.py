# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Source files carry an SPDX licence header.

Documentation, configuration and dependency lists do not; the LICENSE file
covers the repository. The vendored frontend libraries keep the headers of
their own authors.
"""
import pathlib

import pytest

from tests.conftest import REPO_ROOT

SOURCE_SUFFIXES = {".py", ".html", ".js", ".css", ".sh", ".sql", ".mako"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules"}
SKIP_PREFIXES = ("app/static/vendor/",)   # third-party code


def source_files():
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(REPO_ROOT)
        if set(relative.parts) & SKIP_DIRS:
            continue
        if str(relative).startswith(SKIP_PREFIXES):
            continue
        yield relative, path


FILES = list(source_files())


def test_there_are_source_files_to_check():
    """Guards against the list quietly becoming empty."""
    assert len(FILES) > 50


@pytest.mark.parametrize(
    "relative,path", FILES,
    ids=[str(relative) for relative, _ in FILES],
)
def test_source_file_carries_the_licence_header(relative, path):
    text = path.read_text(encoding="utf-8")
    assert "SPDX-FileCopyrightText: 2026 Malte Dreyer" in text, f"{relative}: no copyright line"
    assert "SPDX-License-Identifier: MIT" in text, f"{relative}: no licence identifier"


def test_the_licence_file_exists_and_names_the_holder():
    licence = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License")
    assert "Malte Dreyer" in licence


# The comment syntax each file type needs. A header in the wrong syntax is a
# syntax error in that file: tools/tailwind.config.js once carried a shell-style
# header and broke the stylesheet build, which the test above did not notice
# because it only looks for the text.
COMMENT_START = {
    ".py": ("#",), ".sh": ("#",), ".mako": ("#",),
    ".sql": ("--",),
    ".js": ("/*", "//"), ".css": ("/*",),
    ".html": ("<!--", "{#"),
}


@pytest.mark.parametrize(
    "relative,path", FILES,
    ids=[str(relative) for relative, _ in FILES],
)
def test_header_uses_the_comment_syntax_of_the_file_type(relative, path):
    expected = COMMENT_START.get(path.suffix)
    if expected is None:
        pytest.skip(f"no comment syntax defined for {path.suffix}")

    lines = path.read_text(encoding="utf-8").lstrip().splitlines()
    # A shebang and an encoding declaration have to stay on the first lines,
    # so the header follows them.
    index = 0
    while index < len(lines) and (
        lines[index].startswith("#!") or "coding" in lines[index][:30]
    ):
        index += 1

    header = lines[index] if index < len(lines) else ""
    assert "SPDX" in header, (
        f"{relative}: no SPDX header on line {index + 1}, found {header[:40]!r}"
    )
    assert header.lstrip().startswith(expected), (
        f"{relative}: header starts with {header[:20]!r}, "
        f"expected one of {expected} for {path.suffix}"
    )
