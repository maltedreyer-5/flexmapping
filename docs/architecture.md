# Architecture

## Layers

The application is divided into four layers. The interface layer comprises the
server-rendered admin UI and the generated static site. The API layer provides
the admin API for management operations and the public API for read access. The
service layer holds the processing logic: crawler, prompt engine, entity
normalizer, translation, profile generator, site generator, circuit breaker and
retry manager. The data access layer follows the repository pattern and keeps
SQLAlchemy out of the services.

Repositories load eagerly the relationships that services read after a session
has closed. A lazy load at that point raises an exception. The exception occurs at the
point of use, not at the query that omitted the relationship, which makes the
cause hard to locate.

Persistence consists of PostgreSQL for all master and history data and Redis for
the job queue.

## Processes

A standard deployment runs four containers. `flexmap-app` serves the admin UI,
the admin API, the public API and the site generation endpoints. All of these
are served by one uvicorn process on port 8000; there is no separate frontend
server and no web server in the composition. The admin interface is HTML
rendered on the server, so there is no JavaScript build step and no separate
frontend application.
`flexmap-worker` processes jobs. `flexmap-db` runs PostgreSQL and
`flexmap-redis` runs Redis. The application container and the worker container
share a directory for the generated site; application code, templates and
migrations are mounted read-only.

## Pipeline

Registering a URL creates a crawl job. Everything after that is a chain of
queued jobs, and no processing happens inside an HTTP request.

The crawler fetches the page and, in multi-page mode, a configurable number of
linked subpages on the same domain. It converts the HTML to Markdown and stores
the result on the source. Extract jobs are then created for the prompts of the
source's category.

Each extract job issues one LLM call with the crawled Markdown as context and
stores the answer as the raw result. A validate job then issues a second call
that evaluates that raw result against the same source text and returns a
quality class, a score, a justification and the value to store.

Extractions whose prompt declares an entity type pass through normalization,
where the model selects a canonical entity from the existing inventory.
Depending on the confidence returned, the link is created, a review item is
generated, or the suggestion is discarded.

Translatable fields are translated individually. Once the fields of a source are
available, the profile generator renders the Markdown document from the category
template. Site generation is a separate step and is triggered explicitly.

Each stage writes into its own column, so a later stage can run again without
repeating an earlier one.

## Job priorities

Jobs are held in a Redis sorted set and taken highest priority first. Crawl jobs
have priority 100, extract jobs without dependencies 50, validate jobs 45,
extract jobs with dependencies 40, normalization 30, translation 20 and profile
generation 10.

Translation is placed below every extraction stage because the value it
translates must be final before the translation is worth producing. A job type
missing from the priority map raises an error instead of falling back to a
default, since the default would have been the highest priority.

## Dependency resolution

A prompt may declare that it requires the value of other prompts. Before
extraction begins, the engine determines which prompts have all their
dependencies satisfied, groups them into a wave, and repeats this over the
remainder until no prompt is left. Each wave runs in parallel, and the results
of earlier waves are passed into later prompts as context.

If a wave comes out empty while prompts remain, those prompts form a dependency
cycle. The engine logs this and places the remaining prompts in one final wave
so that processing continues instead of stopping.

## LLM access

All calls pass through a single client that speaks the OpenAI-compatible chat
completions API. The request carries the model name, the messages, the
temperature and the token limit. It carries no tool definitions and no function
definitions, and the model is never asked to decide what runs next. Order,
parallelism and the passing of intermediate results are determined in code
before any call is made.

Three limits apply simultaneously: a semaphore bounds the number of concurrent
calls across the worker pool, a token bucket bounds calls per minute, and a
minimum interval applies per worker.

Behind these sit the circuit breaker and the retry manager. The breaker opens
after a configured number of consecutive failures and blocks further calls for a
configured pause. It then admits exactly one probe request, which decides
whether the circuit closes again or reopens. The retry manager applies
exponential backoff with an upper bound and with jitter; jitter prevents several
workers from retrying in lockstep and arriving at the recovering backend
together. Validation errors are not retried.

Responses are parsed defensively. A self-hosted backend may return a truncated
choice, an empty message or a payload without logprobs, and each of these must
produce a clear error instead of an attribute lookup on a missing value. The
confidence score is derived from the finish reason, from logprobs where the
backend supplies them, and otherwise from the length of the response.

## Static site generation

The site generator reads the published profiles, the category data and the
interface strings, and writes a plain file tree. Each language receives its own
tree, and the English tree contains only those sources for which a translation
exists. The search runs in the browser against a JSON index delivered alongside
the pages, so serving the result requires no backend.

Every internal link is relative to the site root. The same output therefore
works whether it is served at the root by a web server, from a CDN, or under
`/public` by the application itself. Serving it from the application is
convenient while the site is being worked on; in production the directory is
usually handed to a web server or a CDN, and then no backend is involved in
serving the public site.

## Technologies

FastAPI, Uvicorn, Pydantic and pydantic-settings form the application
framework. Data access uses SQLAlchemy 2 with asyncio, asyncpg and Alembic
against PostgreSQL. Redis holds the job queue. The crawler uses httpx,
BeautifulSoup, lxml, html5lib and markdownify. The interface is rendered with
Jinja2 and uses htmx, Alpine.js and Tailwind. Profiles are converted to HTML
with markdown2. Logging uses structlog. Authentication uses Argon2 for password
hashing and itsdangerous for session cookies. Deployment uses Docker and
Compose.

## Scope

The pipeline addresses a single LLM endpoint. There is no routing between
models, no fallback endpoint and no selection of a model per category.
Retrieval consists of the crawled Markdown of one source, passed in whole; no
embedding index or reranking is involved.

Redis holds only the job queue. A restart of Redis loses queued jobs, and the
affected sources remain in their current status until they are re-queued from
the recovery endpoints described in [operations.md](operations.md).

The schema uses the PostgreSQL types `JSONB`, `ARRAY` and `UUID`, PostgreSQL is therefore a requirement.
