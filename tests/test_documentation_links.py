# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Internal documentation links must resolve, including their anchors.

A link to a file that exists but a heading that does not looks correct in
review and lands the reader at the top of the page.
"""
import re

import pytest

from tests.conftest import REPO_ROOT

LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.M)

MARKDOWN = sorted(
    p for p in REPO_ROOT.rglob("*.md")
    if not set(p.relative_to(REPO_ROOT).parts) & {".git", "node_modules"}
)


def anchors(text: str) -> set:
    """GitHub's anchor rule: lowercase, drop punctuation, spaces to hyphens."""
    return {
        re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
        for heading in HEADING.findall(text)
    }


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_links_resolve(path):
    problems = []
    for match in LINK.finditer(path.read_text(encoding="utf-8")):
        target = match.group(2)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        file_part, _, fragment = target.partition("#")
        referenced = (path.parent / file_part) if file_part else path
        if not referenced.exists():
            problems.append(f"missing file: {target}")
            continue
        if fragment and fragment not in anchors(referenced.read_text(encoding="utf-8")):
            problems.append(f"missing anchor: {target}")
    assert not problems, f"{path.relative_to(REPO_ROOT)}:\n  " + "\n  ".join(problems)
