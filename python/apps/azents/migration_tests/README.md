# Azents RDB Migration Test Suite

This suite is intentionally separate from the application test suite under `src/`.
It uses `pytest-alembic` against an isolated PostgreSQL database.

Run it from `python/apps/azents`:

```console
uv run pytest -vv migration_tests
```

When `AZENTS_MIGRATION_TEST_DATABASE_URL` is set, the suite resets and uses that
database. Otherwise, it starts an isolated PostgreSQL 17 testcontainer.

The standard checks cover:

- one Alembic head;
- base-to-head upgrade;
- upgrade/downgrade consistency for revisions introduced after the suite baseline;
- migration-specific PostgreSQL DDL contracts; and
- migration-specific data backfill and fail-fast invariants.
