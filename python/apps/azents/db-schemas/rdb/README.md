# Azents Database Migrations

Alembict uset PostgreSQL t manage.

## uset

### t run

```bash
cd python/apps/azents/db-schemas/rdb
uv run alembic upgrade head
```

### new t create

```bash
cd python/apps/azents/db-schemas/rdb
uv run alembic revision --autogenerate -m "description"
```

### t t t

```bash
uv run alembic history
```

### t t t

```bash
uv run alembic downgrade -1  # t level t
uv run alembic downgrade <revision>  # t t
```
