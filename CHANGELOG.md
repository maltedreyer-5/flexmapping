# Changelog

This file records released versions. It follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0]

First public release.

### Capture

- Crawler with multi-page mode, robots.txt evaluation, per-domain rate limit
  and configurable TLS verification.
- HTML to Markdown conversion; the Markdown is retained with the source.

### Extraction

- One prompt and one LLM call per field.
- Separate validation call per field, returning quality class, score,
  justification and the value to store.
- Confidence threshold per prompt; fields below it enter the review queue.
- Prompt dependencies resolved into parallel waves, with cycle detection.
- Raw result, validated result, manual correction and translation stored in
  separate columns.

### Entity normalization

- Matching against a canonical entity inventory including variants.
- Automatic linking above 0.9 confidence, review item between 0.6 and 0.9.
- Exact matching against the whole inventory; the model-based step receives the
  fifty entities closest to the extracted text.
- Seed script for 95 German universities with coordinates, city and federal
  state.
- Import script for European universities from an external dataset, with a
  configurable country set.

### Translation

- Per-field translation with source and target language as parameters.
- Field label, category and `translation_context` supplied as context.
- Rules protecting proper names, URLs and technical abbreviations.

### Publication

- Markdown and HTML profiles rendered from per-category templates.
- Static site per language: homepage, category pages, detail pages, search
  page, imprint, sitemap, schema.org markup.
- Client-side search over a JSON index covering extracted fields, profile full
  text and entity variants.
- Read-only public API for categories, profiles, search index and statistics.
- `PUBLIC_SITE_URL_PREFIX` sets the path the generated site is served under.

### Configuration

- Categories, field groups, prompts, thresholds and templates defined in YAML.
- Four supplied category definitions: research projects, AI services,
  guidelines, cooperative services.
- Export per category or as a ZIP archive.

### Operation

- Admin interface with dashboard, management views and review queue.
- Account-based access control with the roles `viewer`, `editor` and `admin`.
- Prioritized background jobs; circuit breaker and retry manager around the
  LLM endpoint.
- Recovery endpoints for sources and jobs left mid-pipeline.
- Docker Compose deployment with a separate development override.
- Setup script that generates the secrets, writes `.env`, starts the
  containers and waits for the health endpoint.
