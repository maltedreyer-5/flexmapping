# FlexMapping

FlexMapping extracts structured records from public web pages and publishes
them as a static website.

A content type is defined in a YAML file: its fields, the prompt that extracts
each field, the confidence each field must reach, and the template that renders
the result. The system crawls the registered pages, extracts and validates each
field separately, and generates the site from the reviewed records.

The four category definitions supplied cover research projects, AI services,
guidelines and cooperative services at universities. Further content types are
added as configuration files.

## Extraction

Each field of a category has its own prompt and its own LLM call. A category
with twenty fields produces twenty extract calls, each receiving the crawled
Markdown as context.

A second call validates each raw result against the same source text. It
returns a quality class (`HIGH`, `MEDIUM`, `LOW`, `INSUFFICIENT`), a score
between 0 and 1, a justification, and the value to store.

Per extraction the database holds the raw result, the validated result, a
manual correction and a translation in separate columns.

Consequences:

- Confidence thresholds are set per prompt.
- Fields below their threshold go to the review queue.
- Individual fields can be re-extracted without re-crawling.
- Manual corrections survive later extraction runs.

Prompts may declare dependencies. The engine groups them into waves by
dependency level and runs each wave in parallel. Results of earlier waves are
passed to later prompts as context. Cycles are detected.

## Capabilities

### Capture

- One URL per source, plus optional additional URLs.
- Multi-page mode follows up to `CRAWLER_MAX_PAGES` linked subpages on the same
  domain. Subpages are selected by a rule-based score over link text and URL
  path.
- robots.txt is evaluated. Can be disabled per deployment.
- Rate limit per domain, default 1 request per second.
- TLS verification configurable, for hosts with self-signed certificates.
- HTML is converted to Markdown and stored with the source.

### Entity normalization

Applies to extractions whose prompt declares `entity_type`. Extracted names are
matched against a canonical inventory of entities and their variants.

| Match | Result |
|---|---|
| exact, against canonical name or variant | linked |
| model suggestion, confidence ≥ 0.9 | linked |
| model suggestion, 0.6 to 0.9 | review item |
| model suggestion, < 0.6 | discarded |

Variants such as "TUM" and "Technical University of Munich" resolve to one
entity. Both are searchable.

### Translation

- Per field, one call each.
- Call context: field label, category, and the field's `translation_context`
  where the category configuration defines one.
- Proper names, URLs and technical abbreviations are excluded by explicit rules.
- `translatable` is declared per prompt.

### Configuration

- Categories, field groups, prompts, confidence thresholds and profile
  templates are YAML.
- A new content type is a configuration file, not a code change.
- Export per category or as a ZIP archive.

### Publication

- Markdown and HTML profile per source, rendered from the category template.
- Static site per language: homepage, category pages, detail pages, search
  page, sitemap, schema.org markup.
- Read-only JSON API: categories, profiles, search index, statistics.
- Client-side search over an index containing all extracted fields, the profile
  full text and the entity variants.
- Output is a plain file tree. Served by a web server or a CDN.

### Processing

- Crawl, extract, validate, normalize, translate and generate run as
  prioritized background jobs.
- Circuit breaker: suspends LLM calls after `CIRCUIT_BREAKER_FAILURE_THRESHOLD`
  consecutive failures.
- Retry manager: capped exponential backoff with jitter. Validation errors are
  not retried.
- Load limits on the LLM endpoint: concurrent calls, calls per minute, minimum
  interval per worker.

## Requirements

- Docker and Docker Compose, or Python 3.11+ with PostgreSQL 15+ and Redis 7+
- An OpenAI-compatible chat completions endpoint. The system is designed for a
  locally hosted model; any endpoint speaking that API will do.
- Outbound HTTP access to the sites you intend to crawl.

## Quick start

```bash
git clone https://github.com/maltedreyer-5/flexmapping.git
cd flexmapping
make setup
```

`make setup` generates the session secret, the database password and an
administrator password, writes `.env`, starts the four containers and waits
until the application reports healthy. It prints the administrator password
once; note it down.

One value it cannot generate is the LLM endpoint. Pass it in, or edit `.env`
afterwards:

```bash
bash scripts/setup.sh --llm-url http://your-endpoint:8001/v1 --llm-model your-model
```

The admin interface is then at <http://localhost:8000/admin-ui>. All of it is
served by one process on port 8000: interface, admin API, public API and the
generated site.

Every option of the setup script is documented in
[docs/installation.md](docs/installation.md#the-setup-script).

### Trying it without an LLM endpoint

The interface, the category definitions and the entity inventory work without
one. Crawling, extraction, validation and translation do not.

```bash
# Import European universities into the entity inventory. No LLM involved.
python scripts/import_european_universities.py --countries DE,AT,CH --dry-run
python scripts/import_european_universities.py --countries DE,AT,CH \
  --user admin --password '<the generated password>'
```

You can then browse the four supplied content types under **Categories**,
inspect the prompts that make up each field, and see the entity inventory with
its variants. Registering a URL creates a crawl job that waits for a worker to
reach the LLM.

### Viewing the generated site

The application serves the generated site under `/public/`, so nothing beyond
port 8000 is needed to look at it:

```
http://localhost:8000/public/
```

For the links inside that site to work under this path, generate it with

```
PUBLIC_SITE_URL_PREFIX=/public
```

in `.env`. Leave the value empty when a web server or a CDN serves the
directory at the root, which is the production arrangement.

### Development

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Publishes the database and cache ports on `127.0.0.1`, enables auto-reload,
`DEBUG` and the interactive API docs at `/docs`.

## Security

Intended for operation within an organisation's network, behind a reverse proxy
providing TLS.

The admin interface and the admin API require an account.

| Role | Permissions |
|---|---|
| `viewer` | read access to the management views |
| `editor` | plus sources, extractions, review queue, re-extraction of single sources |
| `admin` | plus prompts, categories, entity master data, site generation, seeding, factory reset |

Prompts and categories require `admin` because a change to either affects all
subsequent extractions.

- Passwords: Argon2, re-hashed on login when the parameters change.
- Sessions: signed cookies.
- HTTP Basic accepted against the same account store, for scripts.
- Public API: unauthenticated, read-only. Supplies the generated site.

With `ENVIRONMENT=production`, startup aborts if a `CHANGE_ME` placeholder
remains, if `DEBUG` or `DOCS_ENABLED` is enabled, or if the database is
unreachable after all retries.

Threat model, environmental assumptions and reporting procedure:
[SECURITY.md](SECURITY.md).

## Documentation

| | |
|---|---|
| [docs/features.md](docs/features.md) | What the system does, from the operator's point of view |
| [docs/installation.md](docs/installation.md) | Deployment with and without Docker |
| [docs/architecture.md](docs/architecture.md) | Components, pipeline, data flow |
| [docs/configuration.md](docs/configuration.md) | Category definitions and settings |
| [docs/system-impact.md](docs/system-impact.md) | What it changes on the host, and how to undo each change |
| [docs/operations.md](docs/operations.md) | Recurring tasks, with the commands to verify them |
| [docs/glossary.md](docs/glossary.md) | Terms used throughout |
| [docs/design/](docs/design/) | Why certain things are built the way they are |

## Third-party components

Runtime dependencies are pinned in `requirements.txt`. All are permissively
licensed (MIT, BSD or Apache-2.0) with one exception: **psycopg2-binary** is
LGPL with exceptions. It is used only for the synchronous database engine that
Alembic and the health check need.

The admin interface ships three frontend libraries under `app/static/vendor/`,
served locally so that the interface works without outbound internet access:

| Component | Version | Licence |
|---|---|---|
| [htmx](https://htmx.org/) | 2.0.4 | BSD-2-Clause |
| [Alpine.js](https://alpinejs.dev/) | 3.14.9 | MIT |
| [Tailwind CSS](https://tailwindcss.com/) | 3.4.17 | MIT |

The Tailwind stylesheet is built at packaging time from `tools/tailwind.css`;
see [CONTRIBUTING.md](CONTRIBUTING.md) for how to rebuild it.

`CODE_OF_CONDUCT.md` is adapted from the
[Contributor Covenant](https://www.contributor-covenant.org) 2.1 and carries
its licence, CC BY 4.0. Everything else in this repository is MIT.

## Scope

FlexMapping needs an OpenAI-compatible endpoint and PostgreSQL; there is no
rule-based fallback and no support for other databases. The validation stage
rates how well the crawled text supports a value, not whether the statement is
true. Access control is three roles and an account; single sign-on is not
included. The four shipped category definitions are written in German and
produce German output. Capturing sources in another language requires category
files in that language.

[SECURITY.md](SECURITY.md) states the threat model and what is deliberately
out of scope.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). It defines what "checked" means as a
concrete list of commands, and states the architecture invariants: rules whose
violation has no visible symptom.

## Licence

MIT. See [LICENSE](LICENSE).
