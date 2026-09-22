# Features

## Extraction

### One prompt per field

A category defines fields; each field defines a prompt. A prompt asks for one
field and runs as its own LLM call with the crawled Markdown as context. A
category with twenty fields produces twenty extract calls.

### Validation call

A second call evaluates each raw result against the same source text.

| Output | |
|---|---|
| Quality class | `HIGH`, `MEDIUM`, `LOW`, `INSUFFICIENT` |
| Score | 0 to 1 |
| Justification | free text |
| Validated result | the value to store; may differ from the raw result |

### Confidence threshold

Set per prompt via `required_confidence`. Fields below their threshold are
flagged and appear in the review queue; they are not published.

Thresholds are per prompt because fields differ in how reliably they can be read
off a page. An institution name is usually stated outright; a funding volume
often is not.

### Review queue

Lists flagged fields with the source Markdown beside each. A value corrected
there is stored in its own column and marked `is_manual_edit`. Later extraction
runs do not overwrite it unless the request asks for that explicitly.

### Prompt dependencies

A prompt may declare `depends_on`. The engine sorts prompts into waves by
dependency level, runs each wave in parallel, and passes results of earlier
waves into later prompts as context. Cycles are detected and logged; the
remaining prompts are placed in one final wave.

### Stored per extraction

Crawled Markdown, raw result, validated result, manual correction, translation.
Separate columns, individually re-runnable. Re-extracting one field does not
affect the others; regenerating a profile does not re-run extraction.

### Robustness

| Component | Behaviour |
|---|---|
| Circuit breaker | opens after `CIRCUIT_BREAKER_FAILURE_THRESHOLD` consecutive failures, admits one probe request after the timeout |
| Retry manager | capped exponential backoff with jitter; validation errors are not retried |
| Rate limits | semaphore over concurrent calls, token bucket per minute, minimum interval per worker |

## Capture

- One URL per source, plus optional additional URLs.
- Multi-page mode follows up to `CRAWLER_MAX_PAGES` linked subpages on the same
  domain, selected by a rule-based score over link text and URL path.
- robots.txt evaluated; can be disabled per deployment.
- Rate limit per domain.
- TLS verification configurable.
- HTML converted to Markdown. NULL bytes and control characters are removed
  before storage.

## Entity normalization

Applies to extractions whose prompt declares `entity_type` (`university` or
`location`).

| Match | Result |
|---|---|
| exact, against canonical name or variant | linked |
| model suggestion, confidence ≥ 0.9 | linked |
| model suggestion, 0.6 to 0.9 | review item |
| model suggestion, < 0.6 | discarded |

Exact matching runs against the whole inventory. The model-based step receives
the fifty entities closest to the extracted text, scored over the canonical
name and every variant.

Two import scripts fill the inventory: German universities with coordinates,
city and federal state, and European universities from an external dataset.
See [operations.md](operations.md).

## Translation

- One call per field.
- Call context: field label, category, and `translation_context` where the
  category configuration defines one.
- Proper names, URLs and technical abbreviations excluded by explicit rules.
- `translatable` declared per prompt.
- The site is generated once per language.

## Configuration

- One YAML file per category: internal name, display names, field groups,
  active groups, Markdown template, one prompt definition per field.
- Export per category or as a ZIP archive.
- See [configuration.md](configuration.md).

## Output

| | |
|---|---|
| Profile | Markdown and HTML, rendered from the category template |
| Static site | homepage, category pages, detail pages, search page, imprint, sitemap, schema.org markup; one tree per language |
| Search index | JSON, containing all extracted fields, profile full text and entity variants |
| Public API | categories, profiles, search index, statistics; read-only |

## Operating interface

Server-rendered HTML with htmx and Alpine.js. No frontend build step at run
time. Dashboard, management views for categories, prompts, sources, extractions,
entities and profiles, review queue, and triggers for site generation,
translation and maintenance. Roles: `viewer`, `editor`, `admin`.

## Scope

The validation call rates how well the crawled text supports a value, not
whether the statement is true. Entity normalization selects from the existing
inventory and does not create entities. Recapture is triggered by an operator or
an external caller; there is no scheduler. The four supplied category
definitions are written in German and produce German output.
