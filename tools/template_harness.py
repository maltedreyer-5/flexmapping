# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Extraction and write-back harness for HTML templates.

Same principle as tools/i18n_harness.py, applied to Jinja templates: find the
spans that are definitely visible text and record their exact offsets, rather
than searching the file for a phrase.

What counts as visible text:
  * text nodes between tags
  * the attributes a user actually reads: placeholder, title, alt, aria-label
  * string literals inside <script> blocks, which carry confirm() and alert()
    messages and fragments assigned to innerHTML

What is never touched:
  * tag names, attribute names, class lists, ids, URLs
  * anything inside {{ ... }} or {% ... %}, including filter arguments
  * <style> blocks

The last point matters: a Jinja expression such as
    {{ i18n.filters.sort_newest | default('Neueste zuerst') }}
contains German that must be changed, but the surrounding expression must not.
Those live in the i18n YAML files and are handled separately, so expressions
are excluded here rather than half-parsed.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from dataclasses import dataclass, asdict

# Regions that are skipped wholesale.
SKIP_REGIONS = re.compile(
    r"<style\b[^>]*>.*?</style>|<!--.*?-->|\{\{.*?\}\}|\{%.*?%\}",
    re.S | re.I,
)
SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
TAG = re.compile(r"<[^>]+>", re.S)
VISIBLE_ATTR = re.compile(r'\b(placeholder|title|alt|aria-label)="([^"]*)"')
JS_STRING = re.compile(r"'([^'\\\n]*)'|\"([^\"\\\n]*)\"")
JS_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)

# A span is only offered for translation if it contains a letter and is not a
# lone Jinja leftover or punctuation.
MEANINGFUL = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")


@dataclass
class Span:
    path: str
    kind: str      # text | attr | js
    start: int
    end: int
    text: str
    lineno: int


def _masked(source: str) -> str:
    """Replace skipped regions with spaces, preserving every offset."""
    out = list(source)
    for match in SKIP_REGIONS.finditer(source):
        for i in range(match.start(), match.end()):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def _lineno(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def iter_spans(path: pathlib.Path):
    source = path.read_text(encoding="utf-8")
    masked = _masked(source)

    # Script blocks are handled first, then blanked out so the text-node pass
    # does not see their contents as page text.
    script_regions = []
    for block in SCRIPT_BLOCK.finditer(masked):
        body_start = block.start(1)
        for match in JS_STRING.finditer(block.group(1)):
            value = match.group(1) if match.group(1) is not None else match.group(2)
            if not MEANINGFUL.search(value):
                continue
            start = body_start + match.start() + 1
            end = start + len(value)
            yield Span(str(path), "js", start, end, source[start:end], _lineno(source, start))
        # Comments inside script blocks. They are prose like any other comment
        # and were invisible to the string pass above.
        for match in JS_COMMENT.finditer(block.group(1)):
            if not MEANINGFUL.search(match.group(0)):
                continue
            start = body_start + match.start()
            end = body_start + match.end()
            if source[start:end] != match.group(0):
                continue
            yield Span(str(path), "js-comment", start, end, match.group(0), _lineno(source, start))
        script_regions.append((block.start(), block.end()))

    blanked = list(masked)
    for start, end in script_regions:
        for i in range(start, end):
            if blanked[i] != "\n":
                blanked[i] = " "
    blanked = "".join(blanked)

    # Visible attributes, read off the original tags.
    for tag in TAG.finditer(blanked):
        for match in VISIBLE_ATTR.finditer(tag.group(0)):
            value = match.group(2)
            if not MEANINGFUL.search(value):
                continue
            start = tag.start() + match.start(2)
            end = start + len(value)
            if source[start:end] != value:
                continue  # offset disturbed by a masked region; skip rather than guess
            yield Span(str(path), "attr", start, end, value, _lineno(source, start))

    # Text nodes: everything between tags.
    position = 0
    for tag in TAG.finditer(blanked):
        chunk = blanked[position:tag.start()]
        if MEANINGFUL.search(chunk):
            stripped = chunk.strip()
            offset = chunk.index(stripped)
            start = position + offset
            end = start + len(stripped)
            if source[start:end] == stripped:
                yield Span(str(path), "text", start, end, stripped, _lineno(source, start))
        position = tag.end()


def cmd_extract(roots):
    spans = []
    for root in roots:
        for path in sorted(pathlib.Path(root).rglob("*.html")):
            spans.extend(asdict(s) for s in iter_spans(path))
    json.dump({"spans": spans}, sys.stdout, ensure_ascii=False, indent=1)


def cmd_apply(payload_path):
    payload = json.loads(pathlib.Path(payload_path).read_text(encoding="utf-8"))
    by_file = {}
    for span in payload["spans"]:
        if span.get("replacement") is not None and span["replacement"] != span["text"]:
            by_file.setdefault(span["path"], []).append(span)

    changed = 0
    for path_str, entries in sorted(by_file.items()):
        path = pathlib.Path(path_str)
        source = path.read_text(encoding="utf-8")
        for entry in sorted(entries, key=lambda e: e["start"], reverse=True):
            actual = source[entry["start"]:entry["end"]]
            if actual != entry["text"]:
                raise SystemExit(
                    f"ABORT {path}:{entry['lineno']}: source moved since extraction.\n"
                    f"  expected: {entry['text'][:80]!r}\n"
                    f"  found:    {actual[:80]!r}"
                )
            source = source[:entry["start"]] + entry["replacement"] + source[entry["end"]:]
            changed += 1
        path.write_text(source, encoding="utf-8")
    print(f"{changed} spans rewritten in {len(by_file)} files")


def structure_signature(source: str) -> list[str]:
    """Tags and Jinja expressions, in order, with text removed."""
    return re.findall(r"<[^>]+>|\{\{.*?\}\}|\{%.*?%\}", source, re.S)


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    if command == "extract":
        cmd_extract(rest)
    elif command == "apply":
        cmd_apply(rest[0])
    else:
        raise SystemExit(f"unknown command: {command}")
