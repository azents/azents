---
title: "Sequential Input Buffer Preparation Validation Report"
created: 2026-07-12
tags: [backend, engine, api, frontend, testenv, process]
---

# Sequential Input Buffer Preparation Validation Report

## Scope

This report covers the integrated implementation stack through producer, worktree, and legacy cleanup. It records local quality results, deterministic E2E coverage, environment limitations, and the remaining CI evidence required before spec promotion.

## Environment

- Source stack head: `test/sequential-input-validation`, based on `feat/sequential-input-producer-cleanup`
- Python: repository-managed `uv` environments
- TypeScript: repository-managed `pnpm` workspace
- E2E infrastructure: unavailable locally because the Docker Unix socket is absent
- External provider credentials: not required; mandatory scenarios use deterministic fixtures

## Validation Results

| Area | Command | Result |
| --- | --- | --- |
| Backend format, lint, and types | `cd python/apps/azents && uv run ruff check --fix . && uv run ruff format . && uv run pyright` | Pass |
| Backend tests | `cd python/apps/azents && uv run pytest -q` | Pass: 1169 passed, 361 skipped, 5 warnings |
| TypeScript format, lint, and types | `cd typescript && pnpm run format && pnpm run lint && pnpm run typecheck` | Pass |
| E2E format, lint, and types | `cd testenv/azents/e2e && uv run ruff check --fix . && uv run ruff format . && uv run pyright` | Pass |
| Deterministic E2E runtime | `cd testenv/azents/e2e && uv run pytest -q -m 'not live_external' ./src` | Blocked locally before test execution: Docker socket is unavailable |
| Migration runtime | Alembic upgrade against the E2E PostgreSQL fixture | Blocked locally by the same Docker limitation |

The local E2E command produced 153 fixture-setup errors with the common root cause `docker.errors.DockerException: ... FileNotFoundError(2, 'No such file or directory')`. These are environment setup failures rather than product assertions. The deterministic CI E2E job is the required runtime evidence for this phase.

## E2E Coverage

The validation branch strengthens deterministic product-boundary coverage for the highest-risk changes:

- queues two follow-up messages while a turn is active;
- verifies the live pending projection preserves FIFO order;
- verifies durable history and model requests observe the same order;
- recovers completed and failed worktree projections from durable `action_execution_result` events after terminal live state is cleared;
- creates a deterministic invalid-ref worktree failure and verifies no Project is registered;
- verifies terminal worktree failure leaves no live action execution state;
- verifies removed action retry and discard routes return 404 or 405.

Existing deterministic E2E coverage continues to exercise per-turn inference target and reasoning-effort changes, edits, pending deletion, stop/reconnect behavior, subagent messages, and worktree cleanup.

## Primary Matrix Status

| Behavior | Evidence | Status |
| --- | --- | --- |
| Mixed FIFO inputs | Updated chat input buffer E2E | Awaiting deterministic CI runtime |
| Per-turn inference | Existing per-prompt inference E2E plus backend turn-snapshot tests | Awaiting deterministic CI runtime |
| Goal and Skill actions | Sequential processor tests | Pass locally; E2E runtime remains CI-owned |
| Worktree success | Updated worktree lifecycle E2E | Awaiting deterministic CI runtime |
| Worktree failure | New invalid-ref terminal-result assertions | Awaiting deterministic CI runtime |
| Preparation failure | Backend processor and worktree service tests | Pass locally |
| Concurrent acceptance | Session-lock boundary tests | Pass locally |
| Edit and pending deletion | Existing E2E plus backend service tests | Backend pass; awaiting deterministic CI runtime |
| Reconnect | Existing REST history/live E2E | Awaiting deterministic CI runtime |
| Removed contracts | OpenAPI/client regeneration and new route-unavailable E2E assertions | Static checks pass; awaiting deterministic CI runtime |

## Exit Criteria

Validation is complete when the validation PR's deterministic E2E and migration-backed CI jobs pass. Live-provider checks remain optional because the mandatory matrix is deterministic and does not require external credentials.
