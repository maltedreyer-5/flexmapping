# Contributing

## Language

English throughout: code, comments, docstrings, commit messages, documentation,
issues and pull requests.

The interface follows the same rule with one exception. The admin interface is
English only. The generated public site is bilingual, driven by
`app/config/i18n/de.yaml` and `app/config/i18n/en.yaml`; both files must carry
identical key sets, which `tests/test_i18n.py` enforces.

The four supplied category definitions are written in German and produce German
output. Their prompt text is functional: it determines what the model extracts
and in which language. Do not translate it.

## What "checked" means

Two commands. Both must pass before a pull request is opened.

```bash
python -m compileall -q app tests generate_site.py alembic
PYTHONPATH=$PWD python -m pytest tests/ -q
```

`make check` runs both. The CI workflow runs the same two commands and nothing
else, so a green run locally and a green run in CI mean the same thing.

The suite needs neither a database, nor Redis, nor an LLM endpoint.

Changes to the templates additionally require:

```bash
make assets
```

This rebuilds `app/static/vendor/tailwind.min.css` from `tools/tailwind.css`.
CI compares the committed file against a fresh build and fails on a difference.

## Architecture invariants

These rules exist because breaking them produces no error. Each is enforced by a
check in `tests/`.

### String literals in Python are not prose

A string in this codebase may be a dictionary key, a comparison value, an API
field name, a Redis key or a filename. Never change one by searching the file
for its text.

Comments and docstrings are edited through `tools/i18n_harness.py`, which
locates them with the tokenizer and the AST and records their exact character
span. It verifies afterwards that the multiset of all remaining string literals
is unchanged. The same applies to templates via `tools/template_harness.py`.

### Comments describe the code and stand on their own

No German, no references to a history that was never published, no instructions
addressed to a developer. `FIXED:`, `NEU:` and `ADDED:` tell a reader of this
repository nothing, because there is no earlier version to compare against.
Where a comment states a reason, that reason must justify the current state
rather than recount a change. Enforced by `tests/test_comment_hygiene.py`.

### Every module must import

A syntax check does not catch a `NameError` at module level, and it does not
catch a function-local `from app.x import y` naming something that does not
exist. Both occurred here. `tests/test_imports.py` resolves every internal
import, including those inside functions.

### Runtime state stays out of the repository

The generated site, database dumps and `.env` are written at run time.
`.gitignore` is checked against the filenames the code actually writes, not
against the documentation, and the reverse direction is checked too: vendored
assets and `.env.example` must remain visible. A bare `lib/` rule once matched
at any depth and would have silently excluded the vendored frontend files.
Enforced by `tests/test_repository_hygiene.py`.

### Eager loading in repositories

Services read relationships after the session has closed. A lazy load at that
point raises. Load relationships eagerly in the repository, at the query.

### The category YAML files are the single source of truth

Categories and prompts are defined there and synchronised into the database.
Do not add a second seeding path. Four existed at one point and defined
seventeen prompts twice, with independent text.

### Enum definitions live in `app/models.py`

`JobType` and `JobPriority` are defined once, next to the `CheckConstraint`
that must list the same values. A second copy diverged from the first.

## Adding a check

A new check needs a counter-test: a demonstration that it fails when the
condition it guards is violated. A check that cannot be made to fail proves
nothing. Two checks in this suite reported success while broken, in both
directions, before the counter-test was added.

## Pull requests

- One subject per pull request.
- Describe what changes and why. If behaviour changes, say so explicitly.
- Note new dependencies with their licence. The project is MIT; copyleft
  dependencies need discussion first.
- Schema changes require an Alembic migration. Run
  `alembic revision --autogenerate` and check the result: it must be empty
  when the models and the migrations agree.

## Licence headers

Source files carry an SPDX header:

```
# SPDX-FileCopyrightText: 2026 Malte Dreyer
# SPDX-License-Identifier: MIT
```

That means Python, Jinja templates, JavaScript, CSS, SQL, shell scripts and
the Alembic migration template. Use the comment syntax of the file type: `#`,
`--` for SQL, `/* */` for CSS and JavaScript, `{# #}` for Jinja so that the
header does not reach the rendered page.

Documentation, configuration files and dependency lists carry no header. The
`LICENSE` file covers the repository.

The vendored libraries under `app/static/vendor/` keep the headers of their own
authors. `CODE_OF_CONDUCT.md` is adapted from the Contributor Covenant and
carries that project's licence, CC BY 4.0; this is stated in `README.md`.

`tests/test_licence_headers.py` checks every source file.

## Code style

Follow the surrounding code. No formatter is enforced.

- Type hints on public functions.
- `structlog` for logging, with keyword fields rather than formatted strings.
- Timezone-aware datetimes: `datetime.now(timezone.utc)`.
- Repositories for database access; services do not use SQLAlchemy directly.
