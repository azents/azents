---
name: python-quality-check
description: Run Python code quality tools (ruff, the configured type checker, pytest) for an Azents Python subproject. Use when the user asks to check code quality, run linting, type checking, or tests for Python code.
---

# Python Quality Check

Run code quality tools from the relevant Python subproject directory.

## Standard Check

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pytest
```

Run the subproject's configured type checker against the whole subproject:

```bash
uv run pyright                         # azents
uv run ty check --error-on-warning     # other maintained Python projects
```

## Quick Reference

### Backend

```bash
cd /path/to/azents/python/apps/azents
uv run ruff check --fix .
uv run ruff format .
uv run pyright
uv run pytest
```

### Shared Library

```bash
cd /path/to/azents/python/libs/az-common
uv run ruff check --fix .
uv run ruff format .
uv run ty check --error-on-warning
uv run pytest
```

### E2E

```bash
cd /path/to/azents/testenv/azents/e2e
uv run ruff check --fix .
uv run ruff format .
uv run ty check --error-on-warning
uv run pytest
```

E2E tests require Docker.

## Line Length Guidelines

- For LLM prompts, preserve prompt quality. Use `# noqa: E501` or a file-level exception when needed.
- For regular code, fix by breaking lines, using intermediate variables, or multi-line formatting.

## When to Run

- After completing a logical unit of work.
- Before marking any task as complete.
- After adding or modifying type annotations.
- After making changes that could affect existing functionality.
