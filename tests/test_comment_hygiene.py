# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
"""
Comments must be in English, describe the code, and stand on their own.

Three failure modes are checked, each of which was actually present in this
codebase:

* German comments, left over from the internal origin.
* References to a history that was never published. "FIXED: ..." tells a
  reader of this repository nothing, because there is no earlier version to
  compare against, and "NEU" claims novelty in a first release.
* Instructions addressed to a developer rather than descriptions of the code.
  One module consisted of endpoints prefixed with "add these to admin.py",
  which is how it came to be dead on arrival.

The checks run over comments and docstrings only, located through the
tokenizer and the AST. Ordinary string literals are never inspected, because
a German word inside one may well be a dictionary key or a prompt.
"""
import re
import sys

import pytest

from tests.conftest import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "tools"))
from i18n_harness import iter_items, python_files  # noqa: E402

ROOTS = ["app", "alembic", "tests", "tools"]

# "falls" is a German word and an English verb form, so it is excluded here;
# every other entry is unambiguous in a code comment.
GERMAN = re.compile(
    r"[äöüÄÖÜß]|\b("
    r"der|die|das|den|dem|des|und|oder|nicht|wird|werden|kann|muss|soll|"
    r"eine|einen|einem|einer|mit|von|aus|nach|bei|auf|zum|zur|ist|sind|hat|"
    r"haben|keine|kein|nur|auch|noch|wenn|dann|alle|beim|durch|zwischen|"
    r"sowie|dass|sich|bzw|damit|weil|nicht)\b"
)

# Second, independent pattern. The list above is built from function words and
# umlauts, and misses German that happens to contain neither -- "Graph
# aufbauen", "Wellen berechnen", "Daten laden". Eighteen comments survived the
# first sweep for exactly that reason, so this list of verbs and nouns runs
# alongside it rather than replacing it.
GERMAN_NO_MARKERS = re.compile(
    r"\b("
    r"aufbauen|berechnen|erstellen|pruefen|laden|setzen|holen|zeigen|anlegen|"
    r"loeschen|speichern|sortieren|zuordnen|ermitteln|erzeugen|verarbeiten|"
    r"zusammenbauen|einreihen|zerlegen|Wellen|Welle|Zyklische|Zyklisch|"
    r"Abhaengigkeit|Reihenfolge|Auswertung|Zuordnung|Eintraege|Eintrag|"
    r"Anzeige|Ausgabe|Eingabe|Kopfzeile|Fusszeile|Schleife|Stapel|Umbau|"
    r"Bezeichner|Vorgabe|Rueckgabe|Extraktionen|Statistiken|Varianten|Volltext"
    r")\b"
)

HISTORY = re.compile(
    r"\b(FIXED|Fixed|ADDED|IMPROVED|CHANGED|REMOVED|NEU|ERWEITERT|LEGACY|"
    r"since version|previously|formerly)\b"
)

INSTRUCTION = re.compile(
    r"\b(F(Ü|UE)GE|Add this|Copy this|TODO|FIXME|HACK|XXX|paste into|insert into)\b",
    re.I,
)


# This file is excluded from its own checks: it has to spell the forbidden
# patterns out in order to search for them.
SELF = REPO_ROOT / "tests" / "test_comment_hygiene.py"


def all_items():
    for root in ROOTS:
        for path in python_files(REPO_ROOT / root):
            if path.resolve() == SELF.resolve():
                continue
            for item in iter_items(path):
                yield path.relative_to(REPO_ROOT), item


def find(pattern):
    return [
        f"{rel}:{item.lineno}  {item.text.strip()[:90]}"
        for rel, item in all_items()
        if pattern.search(item.text)
    ]


@pytest.mark.parametrize(
    "label,pattern",
    [("German text", GERMAN), ("German text (second pattern)", GERMAN_NO_MARKERS),
     ("reference to unpublished history", HISTORY),
     ("instruction to a developer", INSTRUCTION)],
)
def test_comments_are_clean(label, pattern):
    hits = find(pattern)
    assert not hits, f"Comment or docstring carrying {label}:\n" + "\n".join(hits)


# Templates are covered separately: the harness above reads Python only, and
# two HTML comments carrying "FIXED:" survived the first sweep because of that.
TEMPLATE_DIRS = ["app/templates", "public_templates"]
HTML_COMMENT = re.compile(r"<!--(.*?)-->|\{#(.*?)#\}", re.S)


@pytest.mark.parametrize(
    "label,pattern",
    [("reference to unpublished history", HISTORY),
     ("instruction to a developer", INSTRUCTION)],
)
def test_template_comments_are_clean(label, pattern):
    hits = []
    for directory in TEMPLATE_DIRS:
        for path in sorted((REPO_ROOT / directory).rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            for match in HTML_COMMENT.finditer(text):
                body = match.group(1) or match.group(2) or ""
                if pattern.search(body):
                    line = text.count("\n", 0, match.start()) + 1
                    rel = path.relative_to(REPO_ROOT)
                    hits.append(f"{rel}:{line}  {body.strip()[:80]}")
    assert not hits, f"Template comment carrying {label}:\n" + "\n".join(hits)
