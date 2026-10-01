---
title: "Transaction Ownership Phase 25: Engine Tool Results"
created: 2026-10-01
tags: [backend, engine, tools, architecture, database]
---

# Phase Execution Plan

- Phase: `25, Engine ordinary tool-result admission`
- Branch/base: `refactor/transaction-ownership-261001-13-engine-tool-results`
  → `main` at `1622d02e1` after PR #2024 merged with required CI passed.
- PR boundary: replace the ordinary and generated-file-failure tool-result
  caller-owned session contexts in `engine/events/execution.py` with one
  completed repository operation, while retaining the in-session primitive used
  by existing atomic recovery compositions.
- Inputs: Phase 24 Execution lifecycle operations, PR #2024, and the bounded
  14-context Engine execution checkpoint.
- Deliverables: canonical tool-result identity/finalization in the repository
  layer, completed ordinary/failure admission, unchanged output publication, and
  an updated Engine residual checkpoint.
- Non-goals: successful generated-file metadata admission, model-output
  admission, model-input preparation, terminal Run finalization, public schemas,
  persistence schema, retries, fallbacks, or new locking mechanisms.
- Interfaces: result/call identity validation, deterministic external ID,
  transcript append, active-tool removal, phase selection, owner-generation
  fencing, generated-file cleanup/failure fallback, output publication, errors,
  and cancellation remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`,
  `transaction-260908/ADR-D1` through `ADR-D3`, and
  `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove the assigned direct session contexts from
  `AgentRunExecution`; the new repository receives no service, provider, Engine
  orchestration, filesystem, broker, Runtime, or arbitrary callback dependency.
- Absence verification: assigned direct-session search, canonical symbol search,
  repository import search, transaction-closure tests, generated-file failure
  tests, and output-ordering tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Tool-result operation | `/root` | tool-result operation repository/tests | AgentRun and Event transcript repositories | Completed finalization plus reusable in-session primitive | identity, phase, idempotency, and closure tests |
| ReAct loop migration | `/root` | `engine/events/execution.py`, tests | tool-result operation repository | Ordinary/failure result admission completes before publication | execution and generated-file failure regressions |
| Shared recovery primitive | `/root` | user-stop finalizer import/call site | canonical repository primitive | Existing atomic user-stop repair remains in-session | Worker user-stop tests |
| Engine residual checkpoint | `/root` | phase/master plans and bounded inventory evidence | assigned workstreams | corrected remaining execution classification | direct-session/import searches |

- Integration order: move the database-only finalization primitive to its
  canonical repository module, add the completed operation, migrate ordinary and
  failure call sites, update the user-stop import, add closure tests, update the
  checkpoint, and validate.
- External-effect boundary: generated-file preparation/cleanup and output
  publication remain outside completed repository transactions.
- Independent review: one final read-only diff pass checks identity,
  active-tool/phase mutation, cleanup ordering, owner fencing, and scope drift.
- Final validation: root runs changed-path Ruff/format, focused execution,
  user-stop, and repository pytest, full backend `ty`, full backend pytest,
  pre-commit, direct-session/import searches, and creates the next PR.
- Scope-drift check: preserve result identity, idempotency, phases, active tool
  calls, cleanup, errors, cancellation, and atomic groups; add no lock, queue,
  retry, fallback, API, schema, protocol, dependency, or configuration mechanism.
- Context checkpoint: this phase owns two direct session contexts in
  `events/execution.py`. Successful generated-file result admission and the
  remaining model-input, model-output, and terminal boundaries remain later
  execution batches.

## Implementation Checkpoint

- `EngineToolResultOperationRepository` now owns deterministic tool-result Event
  admission, Run locking, matching active-call removal, and
  `executing_tools`/`appending_events` phase selection in one completed
  transaction.
- The same repository retains an explicit database-only in-session primitive for
  successful generated-file metadata admission and Worker user-stop recovery, so
  those existing atomic groups do not split.
- Generated-file preparation and compensation cleanup remain outside database
  transactions. A failed metadata admission cleans up first, then records the
  ordinary failed tool result through a fresh completed repository operation.
- Result/call ID and wire-dialect validation, deterministic external IDs,
  idempotent append behavior, active-call ownership, output publication order,
  owner fencing, cancellation, and error behavior remain unchanged.
- Assigned direct session contexts are zero. The bounded `execution.py` residual
  is 12 contexts covering model-input preparation, provider/model output and
  successful generated-file admission, and terminal finalization. The new
  repository imports no service, Worker, or Engine orchestration module.
- Focused execution/user-stop/repository validation: 67 tests passed. Full
  backend validation: 6,834 tests passed and 3 skipped. Full backend
  `ty --error-on-warning` passed.
- Final read-only diff review found no identity, phase, active-call, cleanup,
  owner-fencing, type, or scope-drift finding.
- Design delta: `None`.
