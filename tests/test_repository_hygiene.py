# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
No runtime state in the repository, and no leftovers from the internal origin.

Both failure modes are silent. A .gitignore rule that names a file the code
never writes looks correct in review; the mismatch only shows up when the
generated site lands in a commit. Likewise an internal hostname survives any
number of readings until something searches for it.
"""
import re
import subprocess

import pytest

from tests.conftest import REPO_ROOT

# Paths the site generator writes. Taken from the code, not from the docs:
# see StaticSiteGenerator._write_file and _prepare_output_dir.
GENERATED_PATHS = [
    "public/index.html",
    "public/search.html",
    "public/suche.html",
    "public/api.html",
    "public/impressum.html",
    "public/imprint.html",
    "public/sitemap.xml",
    "public/details/00000000-0000-0000-0000-000000000000.html",
    "public/assets/css/style.css",
    "public/assets/data/search-index.json",
    "public/assets/data/entities.json",
    "public/en/index.html",
    "public/.flexmapping-site",
    "backups/flexmap.sql",
    "dump.rdb",
    ".env",
]

# Files that must stay visible. A bare "lib/" rule once matched at any depth
# and would have swallowed vendored assets without a word.
TRACKED_PATHS = [
    ".env.example",
    "app/static/vendor/htmx.min.js",
    "app/static/vendor/tailwind.min.css",
    "app/auth.py",
    "tests/test_repository_hygiene.py",
]


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT, capture_output=True,
    )
    return result.returncode == 0


def _git_available() -> bool:
    return (REPO_ROOT / ".git").exists()


@pytest.mark.skipif(not _git_available(), reason="not a git working tree")
@pytest.mark.parametrize("path", GENERATED_PATHS)
def test_generated_path_is_ignored(path):
    assert _is_ignored(path), f".gitignore does not cover {path}, which the code writes"


@pytest.mark.skipif(not _git_available(), reason="not a git working tree")
@pytest.mark.parametrize("path", TRACKED_PATHS)
def test_required_path_is_not_ignored(path):
    assert not _is_ignored(path), f".gitignore hides {path}, which must be committed"


def test_no_runtime_state_on_disk():
    """A packaged checkout must not carry generated output or secrets."""
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in [REPO_ROOT / "public", REPO_ROOT / ".env", REPO_ROOT / "dump.rdb"]
        if p.exists()
    ]
    assert not offenders, f"Runtime state present in the tree: {offenders}"


# Identifiers from the internal origin of this tool. Kept as a regression
# check because they were removed one by one and are easy to reintroduce by
# copying an old snippet.
FORBIDDEN = [
    r"\bpromptki\b",
    r"PROMPT-KI",
    r"ki-kartierung",
    r"\bfhws\.de\b",
    r"hawki\.",
    r"ai-skills\.tu-berlin\.de",
]

SKIP_DIRS = {".git", "__pycache__", "node_modules", "public", "venv", ".venv",
             ".pytest_cache", "backups"}
SKIP_SUFFIXES = {".min.js", ".min.css"}

# This file has to spell the forbidden patterns out in order to search for
# them, so it is excluded from its own check.
SELF = REPO_ROOT / "tests" / "test_repository_hygiene.py"

# RELEASE-CHECKLIST.md is a handover note that is deleted before the first
# commit and is listed in .gitignore. It names the old identifiers on purpose,
# so that the reader recognises what changed.
HANDOVER = REPO_ROOT / "RELEASE-CHECKLIST.md"

# scripts/create_german_universities.py lists 95 German universities with
# their real domains as seed data for entity normalization. fhws.de is one
# entry among them and is reference data, not a trace of origin. The pattern
# is still checked everywhere else.
ALLOWED = {r"\bfhws\.de\b": {REPO_ROOT / "scripts" / "create_german_universities.py"}}


def _source_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if set(path.relative_to(REPO_ROOT).parts) & SKIP_DIRS:
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        if path.resolve() in (SELF.resolve(), HANDOVER.resolve()):
            continue
        yield path


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_internal_identifiers(pattern):
    rx = re.compile(pattern, re.I)
    exempt = {p.resolve() for p in ALLOWED.get(pattern, set())}
    hits = []
    for path in _source_files():
        if path.resolve() in exempt:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{i}")
    assert not hits, f"Pattern {pattern!r} still present in:\n" + "\n".join(hits[:25])
