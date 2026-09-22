# Operations

Recurring tasks, each with the command that performs it and the command that
shows whether it worked. Commands assume the Compose deployment; without Docker,
drop `docker compose exec app` and run the rest in the virtual environment.

Throughout, `$ADMIN` stands for `-u <username>:<password>` of an account with
the `admin` role.

## Adding sources

In the interface: **Sources → New source**, or **Import all** for a list of
URLs sharing one category.

From the API:

```bash
curl -s $ADMIN -X POST http://localhost:8000/admin/sources \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.edu/project","category_id":1,"multi_page":true}'
```

Check that the pipeline picked it up:

```bash
curl -s $ADMIN http://localhost:8000/admin/recovery/queue-status
docker compose exec db psql -U flexmap -d flexmap \
  -c "select status, count(*) from sources group by status order by 1"
```

A source stays in `pending` only as long as its crawl job is queued. If it stays
there with an empty queue, see *Stuck sources* below.

## Watching a run

```bash
docker compose logs -f worker
curl -s $ADMIN http://localhost:8000/admin/recovery/queue-status
docker compose exec db psql -U flexmap -d flexmap -c \
  "select quality_class, count(*) from extractions group by quality_class order by 1"
```

A high `INSUFFICIENT` count usually indicates that the crawl produced little
usable text. Check the stored Markdown of an affected source before changing
prompts.

## Reviewing low-confidence results

**Review** in the interface lists every field below its threshold with the
source Markdown beside it. A correction there is stored as a manual edit.

How many are waiting:

```bash
docker compose exec db psql -U flexmap -d flexmap -c \
  "select count(*) from extractions e join prompts p on p.id = e.prompt_id
   where e.confidence < p.required_confidence"
```

## Re-extracting after a prompt change

Changing a prompt does not change existing values. Either re-extract one source:

```bash
curl -s $ADMIN -X POST http://localhost:8000/admin/sources/<source_id>/re-extract
```

or every source of a category, through **Sources → Re-extract all**.

Verify that new extractions were written:

```bash
docker compose exec db psql -U flexmap -d flexmap -c \
  "select max(updated_at) from extractions"
```

Manual edits survive unless the request explicitly asks to overwrite them.

## Generating and publishing the site

Publishing and generating are separate. A profile is included only once it is
marked published.

```bash
curl -s $ADMIN -X POST http://localhost:8000/admin/steckbriefe/publish-all
curl -s $ADMIN -X POST http://localhost:8000/admin/generate-site
```

Verify:

```bash
ls -la public/                       # index.html, details/, assets/, en/
cat public/.flexmapping-site         # the marker that permits the next run
grep -c '<url>' public/sitemap.xml
python -c "import json;print(len(json.load(open('public/assets/data/search-index.json'))))"
```

Look at the result without a web server:

```
http://localhost:8000/public/
```

The application serves `PUBLIC_SITE_DIR` under that path. The links inside the
site follow `PUBLIC_SITE_URL_PREFIX`, so set it to `/public` when the site is
meant to be viewed this way, and leave it empty when a web server or CDN serves
the directory at the root. Changing the value requires regenerating the site.

The output directory is emptied at the start of every run. If a run aborts
before writing, regenerate; the directory holds nothing worth restoring.

## Translating

```bash
curl -s $ADMIN -X POST 'http://localhost:8000/admin/translations/run?limit=100'
curl -s $ADMIN http://localhost:8000/admin/translations/stats
```

Only fields whose prompt sets `translatable: true` are translated. The English
site contains only sources that have a translation, so generate the site again
after a translation run.

## Stuck sources and jobs

Redis holds the queue. If Redis is restarted or flushed, queued jobs are gone
while the sources that owned them stay in `pending`, `crawled` or `extracting`.

Find them:

```bash
curl -s $ADMIN http://localhost:8000/admin/recovery/queue-status
```

Re-queue:

```bash
curl -s $ADMIN -X POST http://localhost:8000/admin/recovery/requeue-all-stuck
```

Individual states have their own endpoints: `requeue-pending-sources`,
`requeue-crawled-sources`, `requeue-extracting-sources`. Re-queueing costs LLM calls. Check the count first.

To discard queue entries whose source no longer exists:

```bash
curl -s $ADMIN -X DELETE http://localhost:8000/admin/recovery/clear-stuck-jobs
```

## Populating the entity inventory

Entity normalization matches extracted institution names against this
inventory. An institution that is absent stays unlinked, so the inventory is
filled before the first extraction run.

Two scripts are supplied. Both use the admin API and require an account with
the `admin` role.

German universities, including coordinates, city and federal state:

```bash
python scripts/create_german_universities.py \
  --url http://localhost:8000 --user admin --password '<password>'
```

European universities from an external dataset. The dataset supplies name,
country and domains; it supplies neither coordinates nor student numbers, so
those fields stay empty:

```bash
# See what would be imported, without writing anything
python scripts/import_european_universities.py --dry-run

# Restrict to specific countries
python scripts/import_european_universities.py --countries DE,AT,CH --dry-run

# Import. The default country set is EU-27, EFTA and the United Kingdom.
python scripts/import_european_universities.py \
  --url http://localhost:8000 --user admin --password '<password>'
```

Verify:

```bash
docker compose exec db psql -U flexmap -d flexmap -c \
  "select count(*) from entities where entity_type = 'university'"
docker compose exec db psql -U flexmap -d flexmap -c \
  "select count(*) from entity_variants"
```

Running a script twice is safe: an institution that already exists is reported
as such and skipped.

The inventory can hold thousands of entities. Exact matching, including
variants, runs against all of them. The model-based step receives the fifty
entities closest to the extracted text, selected by name similarity.

## Backing up

Nothing is backed up automatically. `./backups` is mounted into the database
container for this purpose.

```bash
docker compose exec db pg_dump -U flexmap -d flexmap -F c -f /backups/flexmap-$(date +%F).dump
ls -lh backups/
```

Restoring into an empty database:

```bash
docker compose exec db pg_restore -U flexmap -d flexmap --clean --if-exists /backups/<file>.dump
docker compose exec db psql -U flexmap -d flexmap -c "select count(*) from sources"
```

The generated site is not worth backing up; regenerate it.

## Adding an operator account

There is no user management screen. Accounts are created in the database:

```bash
docker compose exec app python -c "
import asyncio
from app.database import AsyncSessionLocal
from app.models import User, Role
from app.auth import hash_password
async def main():
    async with AsyncSessionLocal() as s:
        s.add(User(username='name', password_hash=hash_password('password'),
                   role=Role.EDITOR.value))
        await s.commit()
asyncio.run(main())"
```

Verify, and check the role:

```bash
docker compose exec db psql -U flexmap -d flexmap -c \
  "select username, role, is_active from users order by username"
```

Roles are `viewer` (read only), `editor` (curate sources, extractions, review
queue) and `admin` (configuration, entity master data, destructive operations).

## Applying a schema migration

```bash
docker compose exec app alembic current
docker compose exec app alembic upgrade head
docker compose exec app alembic current
```

Back up first. There is no automatic rollback.

## Scope

Every task here is triggered; nothing runs on a schedule. Progress on a long run is visible as the queue length. Account management is a database operation. There is no screen for it and no
password reset.
