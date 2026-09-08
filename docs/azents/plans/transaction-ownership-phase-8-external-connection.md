---
title: "Transaction Ownership Phase 8: External Channel Connection"
created: 2026-09-08
tags: [backend, architecture, database, external-channel]
---

# Phase Execution Plan

- Phase: 8, External Channel connection create, configuration read, and health
  persistence.
- Branch/base:
  `refactor/external-channel-connection-transactions-260908` →
  `refactor/title-repository-transactions-260908`.
- PR boundary: one bounded replacement of the four database lifetimes currently
  owned by `services/external_channel/connection.py`.
- Inputs: requester transaction rules;
  [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md),
  revision 1; and the 2026-09-08 External Channel transaction audit.
- Deliverables: typed completed repository operations for Slack and Discord
  connection creation, connection configuration read, and generation-fenced
  health persistence; no `SessionManager` dependency or database context remains
  in the connection service.
- Non-goals: management, access, ingress, disconnect lifecycle, provider
  activation, provider API changes, credential format changes, schema changes,
  or generic repository transaction wrappers.
- Mechanisms: M1, M2, M3, M4, M5.
- Authorities: `transaction-260908/REQ-1` through `REQ-5`;
  `transaction-260908/ADR-D1` through `ADR-D3`.
- Design delta: None.

| Workstream | Owner | Owned paths | Dependencies / output | Validation |
| --- | --- | --- | --- | --- |
| Connection operation persistence | `/root/impl-external-connection` | `repos/external_channel/**` operation/data/tests required for the four bounded operations | Existing narrow external-channel primitives compose within repository-owned transaction boundaries and return completed typed data | Atomic creation rollback, missing/cross-workspace read behavior, CAS/generation health outcomes |
| Connection orchestration and dependency wiring | `/root/impl-external-connection` | `services/external_channel/connection.py`, its tests, directly required callers/DI | Validation, credential preparation, workspace/provider identity, secret handling, error mapping, and provider effects remain in the service with no active DB transaction | Service ownership absence and provider caller has no active transaction |
| Current-behavior specification | `/root/impl-external-connection` | External Channel domain/lifecycle specs | Code paths, verification date, version, and changelog reflect repository-owned connection operations without semantic change | Spec frontmatter and behavior review |

## Operation Boundaries

1. Slack connection creation validates/prepares credentials before one
   repository-owned atomic write returns the created connection.
2. Discord connection creation validates/prepares credentials and configuration
   before one repository-owned atomic write returns the created connection.
3. Validation reads one completed connection configuration before decrypting
   credentials and calling Slack outside every database transaction.
4. Provider health result persists through one completed
   generation-fenced repository operation. Its stale result preserves the
   existing state-changed outcome.

The new `repos/external_channel/connection.py` operation repository may compose
multiple lower external-channel persistence primitives when one operation has one
database-only atomic outcome. That new operation module must not import a service,
accept a generic transaction callback, expose a live session alias, or invoke
provider code. The service remains the orchestration boundary and is not relocated
wholesale. Pre-existing service imports in other External Channel repository modules,
including `data.py` and `repository.py` imports of `ProviderEffectPlan`, are legacy
residual debt outside this bounded slice. Scheduled PR #1728 moves that contract to
`core` in a sibling stack; Phase 8 must not refactor it independently.

## Removal and Absence Verification

Remove the connection service's `SessionManager[AsyncSession]` injection and its
four `async with session_manager()` database contexts. Replace the exposed
session-taking composition with named typed repository operations. Search confirms
that the service neither owns a transaction nor passes a live database session, and
that the new `repos/external_channel/connection.py` operation module imports no
service code. Existing service-import debt in other External Channel repository
modules is recorded above as out-of-scope legacy residual work.

## Integration and Review

Run focused deterministic tests, changed-path Ruff and format checks, full backend
`ty` check, normal staged pre-commit, and full relevant tests. Request the
independent read-only stable-diff review from `/root/tx-review`. Review verifies
the exact four context removals, rollback behavior, workspace/provider and
generation fences, provider effect staging, secret boundaries, and no scope
expansion. No commit, push, PR, merge, or live-infrastructure operation is part
of this phase.

## Context Checkpoint

The 2026-09-08 audit records 141 baseline External Channel service transaction
contexts. This phase removes four from `connection.py`; the local branch
inventory now finds 29 External Channel service modules with direct
`SessionManager[AsyncSession]` ownership, down from the audit baseline of 30.
The requester-requested program-level residual of 26 must be confirmed only when
the other bounded External Channel phases are integrated. Neither residual is
hidden by a generic wrapper.
