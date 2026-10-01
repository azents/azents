---
title: "Transaction Ownership Phase 24: Engine Execution Lifecycle"
created: 2026-10-01
tags: [backend, engine, execution, lifecycle, architecture, database]
---

# Phase Execution Plan

- Phase: `24, Engine execution phase and pin operations`
- Branch/base: `refactor/transaction-ownership-261001-12-engine-execution`
  → `refactor/transaction-ownership-261001-11-engine-compaction` at
  `5fdb93910` while PR #2022 remains open with required CI passed.
- PR boundary: replace the completed phase-update, conditional stopping-update,
  and model-file pin session contexts in `engine/events/execution.py`, and remove
  the session scope around pure cancelled-result projection.
- Inputs: Phase 23 Compaction operations, PR #2022, and the bounded
  18-context Engine execution checkpoint.
- Deliverables: completed execution lifecycle repository operations, unchanged
  post-commit phase publication, unchanged owner-bound pin authority, and an
  updated Engine residual checkpoint.
- Non-goals: model-input preparation, provider/model output admission, generated
  file admission, tool-result finalization, terminal Run finalization, public
  schemas, persistence schema, retries, fallbacks, or new locking mechanisms.
- Interfaces: phase values and timestamps, active-tool projections, conditional
  STOPPING transition, phase publication ordering, ModelFile pin identities,
  owner-generation fencing, cancellation, and errors remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`,
  `transaction-260908/ADR-D1` through `ADR-D3`, and
  `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove the assigned direct session contexts from
  `AgentRunExecution`; the new repository receives no service, provider, Engine
  orchestration, filesystem, broker, Runtime, or arbitrary callback dependency.
- Absence verification: assigned direct-session search, repository import
  search, phase publication ordering tests, owner-bound pin tests, cancellation
  tests, and transaction-closure tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Execution lifecycle operations | `/root` | execution operation repository/tests | AgentRun and ModelFile pin repositories | Completed phase, conditional stopping, and pin operations | transaction closure and conditional update tests |
| ReAct loop migration | `/root` | `engine/events/execution.py`, tests | lifecycle operation repository | No caller-owned transaction for assigned operations; publication stays after commit | execution phase, compaction, tool cancellation, and pin regressions |
| Engine residual checkpoint | `/root` | phase/master plans and bounded inventory evidence | assigned workstreams | corrected remaining execution classification | direct-session/import searches |

- Integration order: define detached lifecycle results, implement completed
  operations, migrate ordinary phase updates and conditional STOPPING, migrate
  ModelFile pins, remove the pure cancelled-result session scope, add repository
  tests, update the checkpoint, and validate.
- External-effect boundary: phase publication remains after the completed phase
  operation returns. No external effect is added to repository transactions.
- Independent review: one final read-only diff pass checks owner fencing,
  publication ordering, pin scope, cancellation, and scope drift.
- Final validation: root runs changed-path Ruff/format, focused execution and
  repository pytest, full backend `ty`, full backend pytest, pre-commit,
  direct-session/import searches, and creates the next stacked PR.
- Scope-drift check: preserve execution phases, timestamps, active tool calls,
  ModelFile pins, errors, cancellation, and atomic groups; add no lock, queue,
  retry, fallback, API, schema, protocol, dependency, or configuration mechanism.
- Context checkpoint: this phase owns four direct session contexts in
  `events/execution.py`. Model-input preparation, output admission,
  tool-result/generated-file admission, and terminal finalization remain later
  execution batches.

## Implementation Checkpoint

- `EngineExecutionOperationRepository` owns completed ordinary phase updates,
  RUNNING-guarded phase updates, and ModelFile pin admission. Each operation
  closes its owner-bound transaction before returning detached timestamps or
  update status.
- `AgentRunExecution` publishes phase changes only after the completed phase
  operation returns. The user-stop STOPPING path preserves its current Run-status
  guard and publishes nothing when the Run already became terminal.
- ModelFile identities are still collected from the final compacted/pre-lowered
  transcript and pinned under the same execution owner before external
  request-local materialization and model-call preparation.
- Cancelled tool-result projection is now pure and opens no database scope; the
  subsequent ordinary result-finalization operation retains owner fencing and
  durable idempotency.
- Assigned direct session contexts are zero. The bounded `execution.py` residual
  is 14 contexts covering model-input preparation, provider/model output
  admission, tool-result/generated-file admission, and terminal finalization.
  The new repository imports no service, Worker, or Engine orchestration module.
- Focused execution/repository validation: 62 tests passed. Full backend
  validation: 6,831 tests passed and 3 skipped. Full backend
  `ty --error-on-warning` passed.
- Final read-only diff review found no owner-fencing, publication-order, pin,
  cancellation, type, or scope-drift finding.
- Design delta: `None`.
