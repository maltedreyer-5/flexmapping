## What changes

## Why

## Behaviour

- [ ] No change in behaviour; this is text, metadata or structure only
- [ ] Behaviour changes. Described above, including what an existing
      deployment will notice.

## Checks

- [ ] `make check` passes
- [ ] Templates changed: `make assets` run and the result committed
- [ ] Schema changed: Alembic migration added, and
      `alembic revision --autogenerate` afterwards produces an empty migration
- [ ] New dependency: licence stated, compatible with MIT
- [ ] New check added: counter-test included, showing it fails when violated
