# System impact

What FlexMapping changes on the machine it runs on, and how to undo each
change. Nothing here is hidden behind an installer: every item is a file, a
container, a volume or a database object you can inspect and remove yourself.

## With Docker Compose

This is the default deployment. Everything it creates carries the `flexmap`
prefix.

| What | Where | Removing it |
|---|---|---|
| Four containers | `flexmap-db`, `flexmap-redis`, `flexmap-app`, `flexmap-worker` | `docker compose down` |
| One bridge network | `flexmap` | `docker compose down` removes it |
| Two named volumes | `<project>_postgres_data`, `<project>_redis_data` | `docker compose down -v`. **Deletes all captured data.** |
| Two images | built from `Dockerfile` | `docker compose down --rmi local` |
| One published port | `8000/tcp` on all host interfaces | Change or remove the `ports` entry for `app` |
| Generated website | `./public/` in the repository directory | Delete the directory; it is rewritten on every generation run |
| Database dumps | `./backups/`, mounted into the db container at `/backups` | Delete the files you no longer need |

The database and cache ports are **not** published. The development override
(`docker-compose.dev.yml`) publishes them, bound to `127.0.0.1`.

To remove everything including the captured data:

```bash
docker compose down -v --rmi local
rm -rf public backups
```

Verify that nothing is left:

```bash
docker ps -a --filter name=flexmap          # expect no rows
docker volume ls --filter name=postgres_data --filter name=redis_data
docker network ls --filter name=flexmap     # expect no rows
```

## Without Docker

| What | Where | Removing it |
|---|---|---|
| Python packages | the virtual environment you created | Delete the environment directory |
| Database schema | 14 tables plus `alembic_version` in the configured database | `alembic downgrade base`, then `DROP DATABASE` if the database was created for this |
| Redis keys | `job:<id>`, `job_queue`, `job_id_counter` | See below |
| Generated website | the directory in `PUBLIC_SITE_DIR` | Delete it |
| Log output | stdout | Wherever your service manager sends it |

Redis keys are unprefixed by default. If FlexMapping has a Redis database to
itself, `redis-cli -n <db> FLUSHDB` is enough. If it shares one, remove the
keys individually:

```bash
redis-cli DEL job_queue job_id_counter
redis-cli --scan --pattern 'job:*' | xargs -r redis-cli DEL
```

Set `REDIS_KEY_PREFIX` before first use to avoid the ambiguity entirely.

## What it does not touch

- No files outside the repository directory, `PUBLIC_SITE_DIR` and the Docker
  volumes.
- No system-wide configuration, no systemd units, no cron entries, no
  `/etc` files.
- No changes to the machine's network configuration beyond the published port
  and the Docker bridge network.
- No outbound connections other than to the sites you register as sources, the
  configured LLM endpoint, and the package registries at build time.

## The one destructive surprise

`PUBLIC_SITE_DIR` is emptied on **every** site generation run. A marker file named `.flexmapping-site` guards it. If the directory is
non-empty and carries no marker, generation stops instead of deleting. That protects against a
mistyped path, but not against pointing the variable at a directory you use for
something else and then creating the marker yourself.

Give the generated site a directory of its own.

## Scope

This describes a default deployment. Reverse proxy, TLS certificates and firewall rules are configured and removed
separately. Where PostgreSQL or Redis
are shared with other applications, the database objects and key names listed above identify FlexMapping's data.
Setting `REDIS_KEY_PREFIX` before first use avoids the ambiguity. Backups of the Docker volumes taken by other infrastructure are unaffected by
removing the volumes.
