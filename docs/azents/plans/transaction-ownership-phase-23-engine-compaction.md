---
title: "Transaction Ownership Phase 23: Engine Compaction"
created: 2026-10-01
tags: [backend, engine, compaction, architecture, database]
---

# Phase Execution Plan

- Phase: `23, Engine compaction operations`
- Branch/base: `refactor/transaction-ownership-261001-11-engine-compaction`
  → `refactor/transaction-ownership-261001-10-engine-execution-output` at
  `db3c17034` while PR #2021 remains open with required CI passed.
- PR boundary: replace the two caller-owned compaction session contexts in
  `engine/events/filters.py` with typed completed prepare and finalize repository
  operations.
- Inputs: Phase 22 Provider Output operations, PR #2021, and the bounded
  20-context/2-file Engine direct-literal checkpoint.
- Deliverables: a detached compaction plan snapshot, one atomic finalization
  operation, preserved model-operation success and Tool Search reset composition,
  and an updated Engine residual checkpoint.
- Non-goals: remaining `events/execution.py` ownership, provider summary or hook
  behavior, transcript projection, compaction policy, public schemas,
  persistence schema, retries, fallbacks, or new locking mechanisms.
- Interfaces: head/tail stale-plan fencing, marker-before-summary append order,
  summary payload, model-input-head movement, model-operation success settlement,
  Tool Search working-set clearing, owner-generation fencing, errors,
  cancellation, and rollback remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`,
  `transaction-260908/ADR-D1` through `ADR-D3`, and
  `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove direct session-manager and live-session callback
  composition from `EventCompactor`; repository operations receive no service,
  provider, hook, Engine orchestration, filesystem, broker, Runtime, or arbitrary
  callback dependency.
- Absence verification: assigned direct-session and callback searches,
  repository-to-service and repository-to-Engine-orchestration import searches,
  transaction-closure tests, stale-plan regressions, and atomic rollback tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Compaction persistence operations | `/root` | compaction operation repository/data/tests | Session, transcript, Run, candidate-health, and Toolkit State repositories | Completed plan read and atomic summary finalization | repository boundary, ordering, stale-plan, and rollback tests |
| Event compactor migration | `/root` | `engine/events/filters.py`, protocols, tests | compaction operation repository | External summary and enrichment between detached prepare/finalize operations | compactor and adapter regressions |
| Atomic completion composition | `/root` | model-operation completion repository and Worker delegation | existing owner-generation and candidate-health predicates | Model operation success and Tool Search reset remain inside finalization | completion and owner-takeover regressions |
| Engine residual checkpoint | `/root` | phase/master plans and bounded inventory evidence | assigned workstreams | corrected remaining Engine classification | direct-session/callback/import searches |

- Integration order: define typed plan/finalization inputs, extract the shared
  database-only model-operation completion primitive, implement completed
  compaction prepare/finalize operations, migrate the compactor and adapter
  composition, add repository boundary tests, update Specs, then run the residual
  checkpoint.
- External-work boundary: compaction-start notification, summary provider call,
  and summary enrichment execute only after the prepare operation returns and
  before the finalize operation opens.
- Final transaction: re-lock and revalidate the exact captured model-input head
  and physical non-reverted tail, append marker then summary, move the model-input
  head, settle the active compaction model operation, and clear only the Tool
  Search working set before one commit.
- Independent review: one read-only reviewer inspects the stable integrated diff
  for owner fencing, lock/order preservation, callback removal, stale-plan
  rollback, external-I/O boundaries, and scope drift.
- Final validation: root runs changed-path Ruff/format, focused compaction,
  adapter, Worker, and repository pytest, full backend `ty`, full backend pytest,
  pre-commit, direct-session/callback/import searches, and creates the next
  stacked PR.
- Scope-drift check: preserve compaction selection, payloads, summary budget,
  hooks, authority, lock ordering, errors, retry ownership, cancellation, and
  atomic groups; add no lock, queue, retry, fallback, API, schema, protocol,
  dependency, or configuration mechanism.
- Context checkpoint: this phase owns both direct session contexts in
  `events/filters.py`. The 18 direct contexts in `events/execution.py` remain the
  next Engine execution batch.

## Implementation Checkpoint

- `CompactionOperationRepository` owns the completed model-input-head planning
  read and the final marker/summary/head transaction. The final operation returns
  `None` for a stale head or tail so `EventCompactor` preserves the existing
  `CompactionPlanStaleError` surface after the completed transaction returns.
- `ModelOperationCompletionRepository` now owns the shared database-only success
  settlement primitive. Compaction finalization composes it with Tool Search
  working-set clearing after head movement and before the final commit.
- `EventCompactor` no longer opens sessions or accepts a live-session
  `on_committing` callback. Compaction-start notification, summary provider work,
  and summary enrichment remain between the completed prepare and finalize
  operations with no active compactor transaction.
- Marker-before-summary ordering, covered-tail identity, model-input-head
  movement, owner-generation fencing, candidate-health probe settlement,
  compaction operation removal, Tool Search clearing, stale-plan no-op behavior,
  rollback, and cancellation remain unchanged.
- Assigned `filters.py` direct session contexts are zero, legacy compaction
  live-session callback symbols are zero, and the new repositories import no
  service, Worker, or Engine orchestration module. The bounded Engine residual is
  18 direct session contexts in `events/execution.py`.
- Focused compaction/repository/adapter/ownership/Worker validation: 87 tests
  passed. Full backend validation: 6,828 tests passed and 3 skipped. Full backend
  `ty --error-on-warning` and repository-wide pre-commit passed.
- Final read-only diff review found no authority, ordering, external-I/O,
  rollback, type, or scope-drift finding.
- Design delta: `None`.
