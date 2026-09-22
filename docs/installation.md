# Installation

## Requirements

| | |
|---|---|
| Docker deployment | Docker 24+ and the Compose plugin |
| Manual deployment | Python 3.11+, PostgreSQL 15+, Redis 7+ |
| Either way | an OpenAI-compatible chat completions endpoint |

PostgreSQL is required, not merely recommended: the schema uses `JSONB`,
`ARRAY` and the PostgreSQL `UUID` type.

## What serves what

One process serves everything on port 8000: uvicorn, running the FastAPI
application in the `app` container. There is no separate frontend server and no
web server in the Compose file.

| Path | Content |
|---|---|
| `/admin-ui/…` | admin interface, HTML rendered on the server |
| `/admin-ui/static/…` | htmx, Alpine.js, Tailwind, served from the image |
| `/admin/…` | admin API, 65 endpoints |
| `/api/…` | public read-only API |
| `/public/…` | the generated static site, read from `PUBLIC_SITE_DIR` |
| `/health` | health check |

The admin interface is server-rendered HTML with htmx and Alpine.js. There is
no JavaScript build step and no separate frontend application.

The generated static site is written to `PUBLIC_SITE_DIR` as plain files. The
application serves it under `/public/`, so it can be viewed at
<http://localhost:8000/public/> without a web server. In production the same
directory is usually handed to a web server or a CDN instead, and then no
backend is involved in serving the public site at all.

Which of the two is intended decides one setting. `PUBLIC_SITE_URL_PREFIX` is
the path the site will be served under, and every internal link is built from
it: empty for a web server or CDN at the root, `/public` for viewing it through
the application. Changing the value requires regenerating the site.

For a deployment reachable by others, put a reverse proxy in front; see
[Behind a reverse proxy](#behind-a-reverse-proxy). The application terminates no
TLS.

## With Docker Compose

The short way:

```bash
git clone https://github.com/maltedreyer-5/flexmapping.git
cd flexmapping
make setup
```

`scripts/setup.sh` generates the three secrets, writes `.env`, starts the
containers and waits for the health endpoint. It leaves `LLM_BASE_URL` and
`LLM_MODEL` to you; pass `--llm-url` and `--llm-model`, or edit `.env`. Running
it again leaves an existing `.env` alone unless `--force` is given.

The manual equivalent follows, for a deployment where the script does not fit.

```bash
git clone https://github.com/maltedreyer-5/flexmapping.git
cd flexmapping
cp .env.example .env
```

Edit `.env`. Every value beginning with `CHANGE_ME` must be replaced:

| Variable | |
|---|---|
| `SESSION_SECRET` | at least 32 characters; `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `BOOTSTRAP_ADMIN_PASSWORD` | password of the first administrator |
| `LLM_API_KEY` | any non-empty value if your endpoint does not check it |

Set `POSTGRES_PASSWORD` as well; Compose refuses to start without it. Point
`LLM_BASE_URL` and `LLM_MODEL` at your endpoint.

```bash
docker compose up -d
docker compose ps          # four services, all healthy
curl -sf http://localhost:8000/health
```

The admin interface is at <http://localhost:8000/admin-ui>.

On first start the application creates the schema, loads the four shipped
category definitions, and creates the administrator from
`BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD`. Verify:

```bash
docker compose exec db psql -U flexmap -d flexmap \
  -c "select internal_name from categories order by 1"
docker compose exec db psql -U flexmap -d flexmap \
  -c "select username, role from users"
```

### Development

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

The override publishes PostgreSQL and Redis on `127.0.0.1`, turns on
auto-reload, `DEBUG` and the interactive API docs at `/docs`. Do not use it on
a machine others can reach.

## The setup script

`scripts/setup.sh`, also reachable as `make setup`.

It generates the values that can be generated safely, writes `.env`, starts the
containers and waits for the health endpoint. It does not invent an LLM
endpoint.

### Options

| Option | |
|---|---|
| `--llm-url URL` | LLM endpoint, for example `http://localhost:8001/v1` |
| `--llm-model NAME` | model name passed to that endpoint |
| `--admin-password PW` | use this password instead of a generated one |
| `--force` | overwrite an existing `.env` |
| `--no-start` | write `.env` and stop; does not require Docker |
| `-h`, `--help` | show the options |

### What it writes

| Value | Source |
|---|---|
| `SESSION_SECRET` | generated, 48 characters |
| `POSTGRES_PASSWORD` | generated, 24 characters |
| `BOOTSTRAP_ADMIN_PASSWORD` | generated, 20 characters, or `--admin-password` |
| `DATABASE_URL`, `DATABASE_URL_SYNC` | built from the generated database password |
| `LLM_API_KEY` | set to a non-empty value; self-hosted endpoints rarely check it |
| `LLM_BASE_URL`, `LLM_MODEL` | only from `--llm-url` and `--llm-model` |

Secrets are generated with `openssl` where available, otherwise with Python,
otherwise from `/dev/urandom`. The file is written with mode 600.

The administrator password is printed once. After the first start only its
Argon2 hash exists, and there is no reset path other than the database.

### Running it again

An existing `.env` is left alone. `--force` regenerates it, which changes the
session secret and signs everyone out, and changes the database password, which
does not match the password already stored in the database volume. Use `--force`
on a fresh installation only.

### On a machine without Docker

`--no-start` writes `.env` and stops, and skips the Docker check. Useful for
preparing a deployment elsewhere, or for the manual installation below.

## Without Docker

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Adjust `DATABASE_URL` and `DATABASE_URL_SYNC` to point at your PostgreSQL
instance, and `REDIS_URL` at your Redis. Then:

```bash
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The worker runs as a second process:

```bash
python -m app.worker
```

Both read the same `.env`. Without the worker the interface starts and accepts
sources, but nothing is crawled or extracted.

## Behind a reverse proxy

The application binds HTTP only and does not terminate TLS. Put a reverse proxy
in front of it and set `SESSION_COOKIE_SECURE=true` once HTTPS is in place, so
that the session cookie is not sent over plain HTTP.

An nginx fragment:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Restrict `/admin` and `/admin-ui` by network at this layer if the instance is
reachable from more than the machines that should administer it. Do not add a
second HTTP Basic layer in the proxy: the application already authenticates,
and two layers require forwarding the `Authorization` header correctly.

## Production settings

With `ENVIRONMENT=production` the application refuses to start while any
`CHANGE_ME` placeholder remains, or while `DEBUG` or `DOCS_ENABLED` is true.
It also aborts if the database cannot be reached after all retries. The
failure then shows as a restart loop.

Set `PUBLIC_SITE_DIR` to a directory used for nothing else. Its contents are
deleted on every site generation run.

## Verifying the installation

```bash
curl -sf http://localhost:8000/health                       # 200, database connected
curl -s  -o /dev/null -w '%{http_code}\n' \
     http://localhost:8000/admin/sources                    # 401 without credentials
curl -s  -o /dev/null -w '%{http_code}\n' \
     -u admin:<password> http://localhost:8000/admin/sources # 200
curl -s  -o /dev/null -w '%{http_code}\n' \
     http://localhost:8000/docs                             # 404 unless DOCS_ENABLED
curl -s  -o /dev/null -w '%{http_code}\n' \
     http://localhost:8000/public/                          # 404 until a site is generated
```

A `200` on the second line means authentication is not active. Stop and find
out why before putting anything into the instance.

## Scope

Compose is the tested deployment; Kubernetes manifests and service units are
not provided. The LLM endpoint is not contacted at startup, so a wrong
`LLM_BASE_URL` surfaces as failing extract jobs, not as a failed start.
Backups are set up in [operations.md](operations.md), not automatically.
