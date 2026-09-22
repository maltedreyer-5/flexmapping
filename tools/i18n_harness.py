# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Extraction and write-back harness for comments and docstrings.

The rule this exists to enforce: never replace text in Python source by
searching for it. A string in this codebase may be a dictionary key, a
comparison value, an API field name, a Redis key or a filename. Translating one
of those breaks the software silently.

So the harness works the other way round. It uses the language's own syntax to
find the two things that are definitely prose -- comments, via the tokenizer,
and docstrings, via the AST -- and records the exact byte span of each. Nothing
else is ever touched. Write-back happens from the end of the file towards the
beginning, so that earlier spans stay valid.

Afterwards verify_literals_unchanged() compares the multiset of all remaining
string literals before and after the edit. If a single one moved, the run is
rejected.

Usage:
    python tools/i18n_harness.py extract  app > /tmp/items.json
    # translate the "text" fields of the entries, leave everything else alone
    python tools/i18n_harness.py apply    /tmp/items.json
    python tools/i18n_harness.py verify   /tmp/snapshot.json
"""
from __future__ import annotations

import ast
import io
import json
import pathlib
import sys
import token as token_module
import tokenize
from dataclasses import dataclass, asdict
from typing import Iterable, Iterator


@dataclass
class Item:
    """One translatable span, located by absolute character offsets."""
    path: str
    kind: str          # "comment" or "docstring"
    start: int         # inclusive character offset into the source
    end: int           # exclusive
    text: str          # the raw source slice, including quotes or the leading #
    lineno: int


def _offsets(source: str) -> list[int]:
    """Character offset at which each 1-based line starts."""
    offsets = [0, 0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _ast_col_to_char(line: str, byte_col: int) -> int:
    """
    Convert an AST column offset to a character offset.

    ast reports col_offset in UTF-8 *bytes*, while tokenize reports characters.
    Mixing the two silently overshoots the end of any docstring containing a
    non-ASCII character: one byte per umlaut, which is enough to swallow the
    following newline and join two statements onto one line.
    """
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


def iter_items(path: pathlib.Path) -> Iterator[Item]:
    """Yield every comment and docstring in a Python file, with its span."""
    source = path.read_text(encoding="utf-8")
    line_start = _offsets(source)
    lines = source.split("\n")

    def span(start_rc, end_rc) -> tuple[int, int]:
        """Spans from tokenize: columns are already character offsets."""
        (sl, sc), (el, ec) = start_rc, end_rc
        return line_start[sl] + sc, line_start[el] + ec

    def ast_span(start_rc, end_rc) -> tuple[int, int]:
        """Spans from ast: columns are UTF-8 byte offsets and must be converted."""
        (sl, sc), (el, ec) = start_rc, end_rc
        return (line_start[sl] + _ast_col_to_char(lines[sl - 1], sc),
                line_start[el] + _ast_col_to_char(lines[el - 1], ec))

    # Comments: the tokenizer is the only thing that reliably distinguishes a
    # comment from a '#' inside a string literal.
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == token_module.COMMENT:
            start, end = span(tok.start, tok.end)
            yield Item(str(path), "comment", start, end, source[start:end], tok.start[0])

    # Docstrings: only the first statement of a module, class or function
    # counts. A bare string anywhere else is an expression, not documentation,
    # and is left alone.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        const = first.value
        start, end = ast_span((const.lineno, const.col_offset),
                              (const.end_lineno, const.end_col_offset))
        yield Item(str(path), "docstring", start, end, source[start:end], const.lineno)


def literal_snapshot(path: pathlib.Path) -> list[str]:
    """
    Every string literal in the file that is NOT a docstring.

    This is the invariant: translating comments and docstrings must leave this
    multiset untouched. Sorted so that reordering does not register as a
    change; duplicates are kept, because losing one is also a change.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    docstring_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr) \
                    and isinstance(node.body[0].value, ast.Constant) \
                    and isinstance(node.body[0].value.value, str):
                docstring_ids.add(id(node.body[0].value))

    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_ids
    ]
    return sorted(literals)


def python_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def cmd_extract(roots: Iterable[str]) -> None:
    items, snapshot = [], {}
    for root in roots:
        for path in python_files(pathlib.Path(root)):
            items.extend(asdict(i) for i in iter_items(path))
            snapshot[str(path)] = literal_snapshot(path)
    json.dump({"items": items, "snapshot": snapshot}, sys.stdout, ensure_ascii=False, indent=1)


def cmd_apply(payload_path: str) -> None:
    """
    Write translations back.

    Entries carry a "replacement" field; those without one are left untouched.
    Per file, spans are applied in descending order of start offset so that the
    offsets of the not-yet-applied spans remain correct.
    """
    payload = json.loads(pathlib.Path(payload_path).read_text(encoding="utf-8"))

    by_file: dict[str, list[dict]] = {}
    for item in payload["items"]:
        if item.get("replacement") is not None and item["replacement"] != item["text"]:
            by_file.setdefault(item["path"], []).append(item)

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

        ast.parse(source)  # refuse to write anything that no longer parses
        path.write_text(source, encoding="utf-8")

    print(f"{changed} spans rewritten in {len(by_file)} files")


def cmd_verify(payload_path: str) -> None:
    """Compare the literal multiset against the snapshot taken before editing."""
    payload = json.loads(pathlib.Path(payload_path).read_text(encoding="utf-8"))
    failures = []
    for path_str, before in payload["snapshot"].items():
        after = literal_snapshot(pathlib.Path(path_str))
        if after != before:
            lost = [x for x in before if before.count(x) > after.count(x)]
            gained = [x for x in after if after.count(x) > before.count(x)]
            failures.append(f"{path_str}\n    lost:   {lost[:5]}\n    gained: {gained[:5]}")

    if failures:
        print("LITERALS CHANGED -- rejecting this run:\n" + "\n".join(failures))
        raise SystemExit(1)
    print(f"String literals unchanged across {len(payload['snapshot'])} files")


if __name__ == "__main__":
    command, *rest = sys.argv[1:]
    {"extract": cmd_extract, "apply": lambda p: cmd_apply(p), "verify": lambda p: cmd_verify(p)}[command](
        rest if command == "extract" else rest[0]
    )
