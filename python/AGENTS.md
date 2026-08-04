# Python Project Rules

This file covers commands, structure, and workflow for Python code under `python/`. Coding conventions live in `.claude/rules/python-conventions.md`.

## Commands

Run commands from the relevant subproject directory.

```console
$ uv run ruff check --fix .
$ uv run ruff format .
$ uv run pytest
```

Run the configured type checker for the subproject:

```console
$ uv run pyright                         # azents, azents-runtime-control
$ uv run ty check --error-on-warning     # other maintained Python projects
```

Backend app:

```console
$ cd python/apps/azents
$ uv run python -m azents
$ uv run python src/cli/dump_openapi.py
```

Shared library:

```console
$ cd python/libs/az-common
$ uv run ruff check --fix .
$ uv run ruff format .
$ uv run ty check --error-on-warning
```

E2E tests:

```console
$ cd testenv/azents/e2e
$ uv run ty check --error-on-warning
$ uv run pytest ./src
```

## Repository Structure

- Python applications live under `python/apps/`.
- Python shared libraries live under `python/libs/`.
- Each subproject has its own `pyproject.toml` and virtual environment.

## Development Workflow

1. Identify the subproject.
2. Read existing code before editing.
3. Check `.claude/rules/python-conventions.md` for applicable rules.
4. Run quality checks after each logical unit of work.
5. Before completing changes, run the relevant Ruff, configured type checker, and
   Pytest checks.

## Database Migrations

Azents migration directory: `python/apps/azents/db-schemas/rdb/`.

Always update `db-schemas/rdb/revision` with the new revision ID after each migration.

## API Client Generation

Regenerate API clients when routes or schemas change. Do not edit generated client files manually.
