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
- model definitions matching the migration DDL;
- targeted raw-SQL connection-generation trigger/function wiring and required singleton seeds;
- named model CHECK constraints; and
- baseline upgrade/downgrade consistency.

CI also runs `alembic upgrade head` followed by `alembic check` against PostgreSQL
so model drift fails independently of the pytest-alembic wrapper.
