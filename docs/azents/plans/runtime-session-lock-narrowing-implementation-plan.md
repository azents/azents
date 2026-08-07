---
title: "Runtime and Session Lock Narrowing Implementation Plan"
created: 2026-08-07
tags: [runtime, session, postgresql, concurrency, backend]
---
# Runtime and Session Lock Narrowing Implementation Plan

## Authority and Scope

- Existing requirements:
  - [Runtime Deployment Continuity](../requirements/runtime-260804-deployment-continuity.md) (`runtime-260804/REQ-3`, `REQ-4`, `REQ-5`)
  - [Team Session Execution Boundaries](../requirements/session-260724-team-session-execution-boundaries.md) (`session-260724/REQ-1`, `REQ-4`)
  - [User Sessions](../requirements/session-260806-user-sessions.md) (`session-260806/REQ`)
- Existing decisions:
  - [Runtime Deployment Continuity ADR](../adr/runtime-260804-deployment-continuity.md) (`runtime-260804/ADR-D4`, `ADR-D5`)
  - [Team Session Execution Boundaries ADR](../adr/session-260724-team-session-execution-boundaries.md)
  - [User Sessions ADR](../adr/session-260806-user-sessions.md)
- Living Specs:
  - [Agent Runtime Control](../spec/flow/agent-runtime-control.md)
  - [Conversation Domain](../spec/domain/conversation.md)
- Design delta: None.

## Objective

Preserve generation-fenced Runtime control, durable REST idempotency, and transactional
Session admission while reducing PostgreSQL lock conflicts. No public API, schema, or
idempotency contract changes are introduced.

## Delivery Stack

| Phase | Branch | Base | Deliverable | Dependencies |
| --- | --- | --- | --- | --- |
| 1 | `fix/runtime-session-lock-narrowing` | `main` | Runtime lifecycle conditional updates, narrower Runtime locks, and lock-free NetworkPolicy repair validation | None |
| 2 | `fix/runtime-profile-resolution-cas` | Phase 1 | Optimistic Runtime Profile resolution with source snapshots, Runtime CAS, and reconcile convergence | Phase 1 |
| 3 | `fix/session-admission-lock-narrowing` | `main` | Narrower admission locks and removal of redundant Session-creation advisory locking | None |

## Fixed Implementation Boundaries

- `desired_generation` remains an atomic fencing token.
- Lifecycle and desired configuration transitions retain immediate database consistency.
- Provider and Runner interactions remain outside database lock transactions.
- NetworkPolicy repair remains a best-effort one-shot handoff; a later observation
  performs recovery after stale or failed dispatch.
- `chat_write_requests` remains the durable REST idempotency authority.
- No table splitting, generic distributed lock, legacy fallback, migration rewrite,
  or client retry behavior is included.

## Validation Matrix

| Area | Required evidence |
| --- | --- |
| Runtime lifecycle | Repository concurrency/idempotency tests and reconciler tests |
| Profile resolution | Snapshot/CAS conflict tests and reconcile task convergence tests |
| Session admission | Concurrent first-message idempotency tests and FK reference lock tests |
| Quality | Ruff, format, `ty check --error-on-warning`, affected pytest suites |
| Product path | Deterministic User Session E2E when Docker prerequisites are available |

## Removal and Absence Evidence

- Phase 1 removes the NetworkPolicy repair Runtime row lock and verifies no repair
  path retains a transaction-scoped Runtime lock across dispatch.
- Phase 2 removes Runtime Profile source and selection row locks from resolution.
- Phase 3 removes `lock_session_creation_request` and both creation-path calls.
- Repository searches and focused concurrency tests prove the removed lock APIs and
  their references no longer remain authoritative.

## Reviewer

`hardtack` is the independent reviewer for every phase. Review inputs are the
authority references above, each phase execution plan, the current diff, and the
focused concurrency evidence.
