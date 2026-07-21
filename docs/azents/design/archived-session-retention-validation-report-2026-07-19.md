---
title: "Archived Session Retention Validation Report"
created: 2026-07-19
tags: [backend, frontend, scheduler, session, retention, admin, testenv]
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/archived-session-retention-validation-report-2026-07-19.md"
---

# Archived Session Retention Validation Report

## Scope

This report validates the implementation from [Archived Session Retention and Durable Purge](archived-session-retention-and-purge.md) before living-spec promotion.

The validation phase covers:

- Admin retention settings, authorization, preview, and future-only updates;
- root-session archive, archived listing, restore, and hard-delete absence;
- zero-day scheduler eligibility without synchronous deletion;
- archive-time worktree preservation and purge-time worktree deletion;
- backend and TypeScript quality gates; and
- implementation drift against the current living specs.

## Environment

- Date: 2026-07-19
- Python: 3.14.6
- Node.js/pnpm: repository toolchain
- Local container prerequisite: unavailable
  - the Docker CLI is not installed;
  - the Docker socket is absent;
  - Testcontainers fails before fixture startup while fetching the Docker server API version.
- Required credential-free deterministic and Web Surface E2E remain mandatory CI gates.
- The real runtime-provider worktree scenario remains in the optional `runtime_provider` lane, as planned.

## Validation results

| Area | Command or evidence | Result |
| --- | --- | --- |
| Backend formatting/lint | `cd python/apps/azents && uv run ruff check . && uv run ruff format --check .` | Passed |
| Backend typing | `cd python/apps/azents && uv run pyright` | Passed with 0 errors |
| Backend tests | `cd python/apps/azents && uv run pytest` | 1,569 passed, 406 skipped |
| TypeScript workspace | `cd typescript && pnpm run format && pnpm run lint && pnpm run typecheck && pnpm run build` | Passed; 7/7 Turborepo tasks |
| Admin Web focused tests | package lint, typecheck, and test commands | 7 passed |
| Main Web focused tests | package lint, typecheck, and test commands | 32 passed |
| New E2E lint/format | `uv run ruff check ...` and `uv run ruff format --check ...` | Passed |
| E2E typing | `cd testenv/azents/e2e && uv run pyright` | Passed with 0 errors |
| E2E collection | focused `uv run pytest --collect-only -q ...` | 6 tests collected |
| E2E execution | focused deterministic retention tests | Blocked locally before fixture startup because Docker is unavailable; CI required |

## Added E2E coverage

The validation branch adds or updates these product checks:

1. The fresh installation exposes a 30-day retention default only to system administrators.
2. Future-only updates change the policy revision without creating a recalculation application.
3. Archive removes a non-primary root session from the active list and adds immutable archive metadata to the archived list.
4. Restore clears archive metadata and returns the session to the active list before purge fencing.
5. `DELETE /chat/v1/sessions/{session_id}` remains absent.
6. A zero-day archive remains visible immediately after the archive request and disappears only after a manually triggered normal scheduler pass.
7. Admin Web exposes the Retention page and persists a future-only whole-day update.
8. Runtime-provider worktree validation now asserts that archive preserves the dirty worktree and its Azents-owned branch, while durable purge deletes both.

## Implementation and current-spec comparison

| Topic | Implemented behavior | Current spec before promotion | Drift disposition |
| --- | --- | --- | --- |
| Retention policy | DB-backed 30-day default, Unlimited, optimistic revision, future-only or durable recalculation scope | No Admin/system retention contract | Add a dedicated system settings domain spec |
| Archive unit | Complete root `SessionAgent` subtree | Conversation spec describes one non-primary `AgentSession` | Update conversation spec to the root-tree lifecycle unit |
| Archived browser | Separate archived list, immutable snapshot/deadline metadata, restore action | Conversation spec says archived sessions are outside current API/UI | Replace stale statement with current API and Main Web behavior |
| Restore boundary | Allowed only before purge fencing starts | No restore contract | Add restore and conflict semantics |
| Worktree archive behavior | Archive preserves allocations | Conversation spec says archive schedules best-effort worktree cleanup | Replace stale archive cleanup contract |
| Worktree purge behavior | Purge deletes owned paths/branches before DB deletion | No durable purge ordering | Add purge ownership and ordering |
| ExchangeFile ownership | Source and preview rows bind atomically to one root retention unit | File storage spec has ordinary session ownership and TTL only | Add root claim, same-tree access, and purge boundary |
| ModelFile/Artifact cleanup | Purge deletes subtree-owned blobs before metadata cascade | File storage spec documents only ordinary TTL/head-cursor cleanup | Add archived-root purge as an earlier terminal boundary |
| Scheduler tasks | One-minute recalculation and five-minute purge tasks with bounded backoff | Periodic execution spec lists neither task | Add both registry entries, handler summaries, and lease behavior |
| Execution fencing | Archived subtree sessions reject ownership, run transitions, input, command, wake-up, and recovery | Execution-loop spec has no archived-session admission state | Add archived-state fencing rules |
| Permanent deletion | Public hard-delete API/UI absent; internal purge finalization owns deletion | Conversation spec still discusses hard delete constraints | Remove the public hard-delete contract and document internal finalization |
| Zero-day policy | Request path archives successfully; the next scheduler pass owns deletion | No zero-day contract | Add explicit asynchronous eligibility semantics |

No implementation behavior was weakened to preserve the stale specifications. The spec-promotion phase must update the living specs to the validated implementation.

## Findings and fixes

- Fixed stale purge-job reconciliation so unstarted jobs whose schedule identity no longer matches the archived root are cancelled durably, while fenced jobs remain irreversible.
- Fixed Admin progress recovery after reload by returning the active durable application with settings.
- Fixed Admin Save remaining disabled after recalculation completion by invalidating authoritative settings when the application reaches `completed`.
- Fixed Main Web mutation pending-state access and failure-state rendering.
- Corrected the existing runtime-provider E2E expectation from archive-time worktree deletion to archive preservation followed by purge deletion.

## Remaining CI evidence

Before this validation phase is complete, required CI must pass:

- credential-free deterministic E2E, including Admin API and zero-day scheduler purge;
- Web Surface E2E, including the Admin retention page;
- backend and TypeScript checks for every PR in the complete stack.

The optional runtime-provider lane may be skipped only when its declared provider prerequisite is unavailable. When that prerequisite is available, worktree lifecycle failure must fail the lane.
