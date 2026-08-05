---
title: "Unified Python Type Quality Gate"
created: 2026-08-05
tags: [python, typing, ci, architecture]
document_role: primary
document_type: adr
snapshot_id: typing-260805
---

# Unified Python Type Quality Gate

- Snapshot: `typing-260805`
- Requirements: [typing-260805/REQ](../requirements/typing-260805-ty-quality-gate.md)

## Decision Context

The backend application was the final maintained Python project still enforced by Pyright while the repository had already adopted `ty` for other Python projects. The requester requires one active type-quality gate without reducing Ruff, pytest, or contract verification.

## Decisions

### typing-260805/ADR-D1 — `ty` is the sole active Python type checker

**Status:** Accepted on 2026-08-05<br>
**Requirements:** typing-260805/REQ-1, typing-260805/REQ-2

Remove active Pyright dependency, configuration, CI, pre-commit, contributor-instruction, and non-migration source-directive ownership. Use `uv run ty check --error-on-warning` as the type-quality command in the backend app and every maintained Python CI matrix entry.

**Consequences**

- Contributors and CI use one type-check command and one suppression vocabulary.
- `ty` warnings are blocking, matching the established project gate.
- Existing Pyright-specific directives outside immutable migration and historical records are stale and must be removed.

### typing-260805/ADR-D2 — Preserve non-type quality gates and immutable records

**Status:** Accepted on 2026-08-05<br>
**Requirements:** typing-260805/REQ-3

Keep Ruff, pytest, and OpenAPI drift verification unchanged. Do not edit executed Alembic migrations or implemented historical documentation merely to remove inactive Pyright text.

**Consequences**

- The migration changes type-check ownership only; it does not redefine lint, format, test, runtime, or data-migration behavior.
- Historical/migration references may remain as inactive provenance where removal would violate immutability.
