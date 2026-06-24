# azents

Coding conventions for `python/apps/azents/` live in `.claude/rules/python-azents-conventions.md` (plus the broader `python-conventions.md`).

## Commands

```bash
# Development server
cd python/apps/azents && uv run python -m azents

# Tests
cd python/apps/azents && uv run pytest

# Quality checks
cd python/apps/azents && uv run ruff check --fix . && uv run ruff format . && uv run pyright
```

## Database Migrations

azents-specific notes:

- Migration skill loads environment variables from `.env` automatically
- Migration directory: `db-schemas/rdb/`
- Always update `db-schemas/rdb/revision` with the new revision ID after each migration

See the `migration` skill and `.claude/conventions/python/alembic-revision-only.md`.
