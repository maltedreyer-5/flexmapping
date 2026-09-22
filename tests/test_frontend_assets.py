# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
The admin interface must not depend on a CDN.

Operators run this inside institutional networks where outbound access is
restricted or proxied. Three CDN script tags meant the interface silently
degraded there. They also meant the Alpine.js version was resolved at page
load -- and it was loaded twice, from two CDNs, at two different versions.
"""
import re

import pytest

from tests.conftest import REPO_ROOT

VENDOR_DIR = REPO_ROOT / "app" / "static" / "vendor"
ADMIN_TEMPLATES = sorted((REPO_ROOT / "app" / "templates").rglob("*.html"))
REQUIRED_ASSETS = ["htmx.min.js", "alpine.min.js", "tailwind.min.css"]

CDN_PATTERN = re.compile(r"https?://(cdn\.|unpkg\.com|.*\.jsdelivr\.net)", re.I)


@pytest.mark.parametrize("filename", REQUIRED_ASSETS)
def test_vendored_asset_present(filename):
    path = VENDOR_DIR / filename
    assert path.is_file(), f"Missing vendored asset: {path}"
    assert path.stat().st_size > 1000, f"{filename} looks truncated"


@pytest.mark.parametrize("path", ADMIN_TEMPLATES, ids=lambda p: p.name)
def test_no_cdn_references(path):
    hits = [
        f"line {i}: {line.strip()}"
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if CDN_PATTERN.search(line)
    ]
    assert not hits, f"{path.name} still loads assets from a CDN:\n" + "\n".join(hits)


def test_applied_classes_are_in_the_built_stylesheet():
    """
    The nine status and quality classes are declared with @apply in base.html.
    The browser-side Tailwind CDN never processed @apply inside a plain
    <style> block, so they resolved to nothing. They must be present in the
    stylesheet that is built at packaging time.
    """
    css = (VENDOR_DIR / "tailwind.min.css").read_text(encoding="utf-8")
    expected = [
        "status-pending", "status-crawled", "status-extracting",
        "status-completed", "status-failed",
        "quality-high", "quality-medium", "quality-low", "quality-insufficient",
    ]
    missing = [name for name in expected if f".{name}" not in css]
    assert not missing, (
        "Classes missing from the built stylesheet: "
        f"{missing}. Rebuild it; see CONTRIBUTING.md."
    )
