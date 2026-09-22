# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Every internal link of the generated site follows PUBLIC_SITE_URL_PREFIX.

The site is served either at the root by a web server, or under /public by the
application itself. Links were built root-relative regardless, so viewing it
through the application produced a page whose stylesheet, navigation and
language switch all pointed one level too high and returned 404.
"""
import re

import pytest

from tests.conftest import REPO_ROOT

PUBLIC_TEMPLATES = sorted((REPO_ROOT / "public_templates").glob("*.html"))
ROOT_LINK = re.compile(r'(?:href|src)="(/[^"]*)"')


@pytest.mark.parametrize("path", PUBLIC_TEMPLATES, ids=lambda p: p.name)
def test_no_hardcoded_root_links(path):
    """
    A link starting with a literal slash ignores the prefix.

    Links must start with {{ url_prefix }} or {{ site_root }}; the latter for
    the language switch, which has to leave the language segment behind.
    """
    hits = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for match in ROOT_LINK.finditer(line):
            hits.append(f"line {line_number}: {match.group(0)}")
    assert not hits, (
        f"{path.name} links to the root without a prefix:\n  " + "\n  ".join(hits)
    )


def test_prefix_is_configurable():
    from app.config import Settings

    assert Settings(PUBLIC_SITE_URL_PREFIX="").public_site_url_prefix == ""
    assert Settings(PUBLIC_SITE_URL_PREFIX="/public").public_site_url_prefix == "/public"
