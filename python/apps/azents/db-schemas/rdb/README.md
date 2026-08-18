# Azents Database Migrations

Alembic manages the Azents PostgreSQL schema.

## Usage

### Apply migrations

```bash
cd python/apps/azents/db-schemas/rdb
uv run alembic upgrade head
```

### Create a migration

```bash
cd python/apps/azents/db-schemas/rdb
uv run alembic revision --autogenerate -m "description"
```

Always generate migration files with `alembic revision`; do not create migration
files manually.

### Inspect history

```bash
uv run alembic history
```

### Downgrade

```bash
uv run alembic downgrade -1
uv run alembic downgrade <revision>
```
