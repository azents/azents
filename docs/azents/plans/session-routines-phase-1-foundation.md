---
title: "Session Routines Phase 1 Foundation"
created: 2026-10-18
tags: [routine, implementation, plan]
---

# Phase Execution Plan

- Phase: 1 of 5, definition/record and Primary foundation.
- Branch/base: `feat/routine-261018-1-foundation` -> `main` at `f045c138934aedb935baa538af93afc4489762d8`.
- PR boundary: reviewable persistent contracts and safe owner operations; no Scheduler/model/Agent activation yet.
- Inputs: [Requirements](../requirements/routine-261018-session-routines.md), [ADR](../adr/routine-261018-session-routines.md), approved [Design revision 1](../design/routine-261018-session-routines.md), [implementation plan](session-routines-implementation-plan.md).
- Approved Design mechanisms: `M1, M6, M9, M11` within this phase; later integration retains all `M1-M11` authority.
- Authority: REQ-1, REQ-3, REQ-12 through REQ-14; ADR-D2; Design M1/M6/M9/M11; existing ownership and transaction conventions.
- Design delta: None.
- Deliverables: typed content/source/record contracts; exact-prior-content update semantics; Session definition limit and identity safety; definition/work-record models and owner queries; Primary backfill guard and current-owner validation; generated migration/revision; focused unit and PostgreSQL tests.
- Non-goals: live judgment, new event kind, actual Routine tools/dispatch, UI, frontend write API, production migration or publication, new version history, retry/outbox/fallback.
- Interfaces: sources initially Manual; content comparison is exact; result and hint remain self-contained prompt guidance without extra text caps; records have independent objective/notification/delivery outcomes; Primary is nullable Session-owned authority and does not restrict all bindings to one per Session.
- Removal obligations: retain all existing Bindings and Scheduled behavior. No existing Routine implementation to remove. New primary fields must not add a duplicate authoritative destination.
- Absence verification: no connection deletion during backfill, ambiguity raises before mutation, no active Routine execution table, no provider/network I/O inside owner transactions.

| Workstream | Owner | Owned paths | Dependency | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Contracts | /root | `python/apps/azents/src/azents/core/routine*`, focused tests | approved content/record behavior | typed domain data and pure validation | Ruff, ty, unit tests |
| Persistence | /root | `rdb/models/routine*`, `repos/routine*`, tests | contracts | scoped definitions and bounded records, atomic exact update | PostgreSQL integration tests |
| Primary | /root | existing Session/Binding persistence and connection/lifecycle composition; `repos/*primary*`, tests | current Binding ownership | nullable current Primary and safe backfill | zero/one/multiple/foreign/disconnect tests |
| Schema | /root | `db-schemas/rdb/migrations/versions/`, revision pointer | models/Primary | Alembic-generated migration | upgrade/downgrade policy review, graph, migration tests |
| Documents | /root | snapshot trio and these two plans | requester approval | recorded exact authority and phase contract | catalog and trace/link checks |

Integration order: contracts -> models and repositories -> Primary integration ->
migration -> integrated tests and drift check -> stable full-phase review -> root
corrections and affected reruns -> commit and phase PR. Later phases cannot start
before this PR exists.

Independent reviewer: `/root/routine-reviewer`, read-only one-way review of the
complete integrated stable phase diff. Root requests review and makes all changes.

Final validation: focused Ruff/typecheck/pytest, real PostgreSQL transaction and
migration tests, affected existing Session/Binding tests, documentation catalog,
whitespace, migration-head/revision identity and no-secrets diff review. Root
records exact commands/results and any prerequisite failures.

Scope drift: compare phase coverage to M1/M6/M9/M11, reject later-phase activation
and unauthorized behavior, and keep removed/deleted data effects within approved
archive/deletion semantics. No additional approval is requested for equivalent
local field/helper choices.

Context checkpoint: started 2026-10-18 KST. Backend dependencies installed;
Docker available; managed dev environments absent. Reviewer ready. No production
data audit, migration, model call or execution test performed yet. On phase
completion record changed contracts, exact validation and remaining scope here.

Implementation checkpoint, 2026-10-18 KST:

- Added `core/routine.py` contracts, immutable exact-comparison content, Manual
  source, explicit patch, independent objective/notification outcomes, limits and
  detached definition/record types.
- Added definition and retained-record ORM models plus repository primitives;
  owner operations serialize the Session limit and exact updates with ownership
  fences. No active-execution product table was introduced.
- Focused Ruff and ty passed on the current new core/model/repository files.
  `uv run pytest -q src/azents/core/routine_test.py`: 23 passed, two existing
  testcontainers deprecation warnings. These are contract tests, not DB/E2E proof.
- Completed Alembic-generated migration `08a588456917`, revision pointer, Routine
  tables/enums and nullable indexed Primary FK. Primary initialization is composed
  with channel creation; exact disconnect clears it; physical Binding deletion
  sets it null. No existing Binding is removed by designation/backfill.
- Added real PostgreSQL tests for exact content, isolation, owner fencing, limit,
  retention/idempotence, late deletion, notification observations, Primary
  creation/backfill/ambiguity, wrong owners, disconnect and FK cleanup.
- Added actual predecessor-to-head migration tests for zero/one Binding backfill,
  multiple-Binding rejection and inactive/cross-Workspace owner rejection with
  rollback to the predecessor. A test-fixture parameter type conflict was fixed;
  the successful migration assertions were rerun rather than inferred.
- Final root validation: focused Ruff passed; full backend
  `uv run ty check --error-on-warning` passed; focused pytest over Routine core,
  persistence, migrations and existing External Channel repository/work,
  AgentSession repository and Scheduled lifecycle suites: 271 passed in 16.03s,
  with three existing dependency deprecation warnings. This includes 45 new
  tests, not E2E or production data verification.
- Documentation catalog, snapshot links/approval identity and whitespace passed.
  No operational migration, model call or E2E environment execution occurred.
- Initial integrated review found one P2: Binding-first disconnect plus Primary
  Session update opposed archive's Session-first order. Root connected the five
  affected completed terminal DB owners to existing confirmed-abort recovery;
  Single disconnect preserves its prior committed stage and retries only the
  second transaction. No provider effect is inside that recovery boundary.
- Extended owning paths within M11 to External Channel management/revocation
  owner operations and finite locking-policy tests. Added real opposing-writer
  tests forcing either archive or disconnect to be PostgreSQL's deadlock victim.
  Both complete with no stale Primary. This is existing DB contention policy,
  not a new Routine or notification retry mechanism.
- A pre-existing shared lock-observer helper cached `pg_stat_activity` before a
  new waiter backend appeared. The expanded suite exposed this consistently;
  refreshing PostgreSQL's statistics snapshot fixes observation without raising
  timeouts or adding sleeps. The helper's own OAuth tests were included in reruns.
- Corrected root validation: 324 tests passed in 19.39s across the full selected
  Routine, migration, channel, Session, Scheduled, contention, management and
  OAuth observer suites. Full backend ty and focused Ruff passed. Three existing
  dependency warnings remain. No E2E or production-data verification claimed.
- Added current Primary and terminal-contention Spec updates because those
  existing behaviors change in this phase; full Routine spec promotion remains
  phase 5. Complete feature Design delta remains None.
- Targeted re-review identified remaining same-P2 callers in Single first-stage
  disconnect and parent/default changes. Root extracted a separately protected
  first stage and covered default replacement/clear and parent setting mutation;
  finite recovery inventory is now 47 completed DB owners. The public two-stage
  orchestration is not retried as a unit.
- Expanded real deadlock matrix covers Binding disconnect, Single first stage,
  default clear and parent settings, forcing each possible victim (8 cases).
  Repeated confirmed aborts count as repeated fresh attempts, never replay of
  a committed operation. Root full selected regression: 330 passed in 23.79s;
  full backend ty and focused Ruff passed. Targeted matrix/inventory: 10 passed.
- Same reviewer `/root/routine-reviewer` confirmed the original P2 fully closed
  on staged tree `1047ca5b5a6ca39986c5711745d7061574d05e27`; no remaining
  same-cause owner or new security/data-loss/interface issue was identified.
  Root owns the reported tests. Final hooks, commit and first PR are next.
  No later-phase implementation has begun.
