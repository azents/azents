---
title: "Transaction Ownership Phase 26: Engine Model Input"
created: 2026-10-02
tags: [backend, engine, architecture, database]
---

# Phase Execution Plan

- Phase: `26, Engine model-input preparation`
- Branch/base: `refactor/transaction-ownership-261002-14-engine-input` →
  `main` at `4b05fc9f6`, including merged Phase 25 PR #2033.
- PR boundary: one completed repository-owned model-input preparation operation,
  including input-head capture, transcript reads, missing-tool reconciliation,
  PREPARING_INPUT mutation, and attachment/FilePart projection.
- Inputs: completed tool-result repository operation and current input call-path
  evidence. Production pre-lower filtering consists exclusively of two
  database-only availability transformations; compaction is a later external stage.
- Deliverables: detached transcript, repaired Events, and phase timestamp after
  one completed transaction; canonical database-only projection primitives and
  pure payload transformations; removal of the live-session Engine filter API.
- Non-goals: model-output/generated-file admission, terminal finalization,
  mailbox ownership, public schemas, persistent state, retries, configuration,
  provider protocols, or new locking mechanisms.
- Interfaces: preserve input-head selection, result external IDs, scheduled-result
  recovery, active-call reconciliation, owner-generation fencing, DB lock order,
  availability text/payloads, output publication, compaction order, and rollback.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through ADR-D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current Agent Execution Loop Spec.
- Design delta: `None`.
- Removal obligations: remove the assigned application-owned input session and
  input-only session-taking helpers; replace session-taking pre-lower filter
  protocols/classes with explicit repository composition. Update all callers and
  tests to canonical symbols without aliases, re-exports, or general callbacks.
- Absence verification: symbol/caller/import searches, direct-session inventory,
  typed dependency wiring, and transaction-closure/rollback regression tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Input operation and projections | `/root/tx-engine-input` | new input/projection repositories, pure Event projection/cancellation helpers, corresponding tests | existing narrow Run/Transcript/Session/status repositories | completed atomic input operation | closure, rollback, head reuse, scheduled recovery, ownership, projection tests |
| Engine callers and obsolete filter removal | `/root/tx-engine-input` | execution.py, protocols.py, filters.py, engine_adapter.py and related tests | input operation | canonical typed repository invocation; no live-session filter callback | execution, adapter, filter and lowerer regressions |
| Integration and documentation | `/root` | phase/master plans and Agent Execution Loop Spec | stable integrated implementation | bounded checkpoint and delivery | root-owned integrated quality/test/CI validation |

- Integration order: relocate pure transformations; implement concrete DB-only
  projection primitive and input operation; migrate Engine/adapter callers and
  tests; remove obsolete filter and input-helper units; integrate documentation.
- Atomic group: head read → transcript read → missing-tool repair → same-head
  reload → PREPARING_INPUT → Exchange availability → ModelFile placeholder.
  Existing result append-before-Run-lock ordering remains intact.
- External-effect boundary: result/phase publication, compaction preparation and
  summary generation, provider/model work, tools, and Runtime work follow closure.
- Independent review: `/root/phase25-independent-review`, read-only. Root requests
  one complete integrated diff review after implementation and final validation.
- Final validation: root runs focused repository/execution/adapter/filter/tool
  tests, full backend `ty --error-on-warning`, backend pytest, pre-commit,
  removed-symbol/session/import checks, and all applicable required PR CI.
- Scope-drift check: no product, schema, dependency, provider, retry, fallback,
  queue, configuration, or locking changes. No service/Engine orchestration or
  arbitrary application callbacks are accepted by the new repository.
- Context checkpoint: baseline `execution.py` has 12 direct session contexts;
  this phase owns one input context. Output/generated-file admission and terminal
  finalization remain subsequent phases. This does not complete issue #1718.

## Implementation and Validation Checkpoint

- The complete input atomic group now belongs to
  `EngineModelInputOperationRepository`; `EngineInputProjectionRepository`
  composes the two database-only availability transformations. Canonical pure
  helpers retain selection order, payload shapes, and placeholder text.
- Removed the live-session pre-lower filter protocol, pipeline, concrete filter
  classes, and input-only Engine helpers; production symbol/caller search found
  zero remaining references to those removed interfaces.
- Production adapter wiring uses the explicit projection repository; every
  isolated execution fixture explicitly selects no projection, matching its
  existing no-filter behavior. Compaction and publication remain post-commit.
- Root integrated focused validation, including real ownership tests:
  `167 passed`. Full backend validation: `6802 passed, 3 skipped`.
  The three skips are the memory implementations of one Redis-specific retention
  test and two Redis-specific stale-index tests; their Redis cases run normally.
- Full backend `ty --error-on-warning`, full pre-commit, and `git diff --check`
  passed. Initial Runtime process handles disappeared before two jobs completed;
  those incomplete logs were not accepted as evidence. Completed reruns record
  explicit zero exit markers and full summaries.
- `execution.py` direct session contexts are reduced from 12 to 11. Remaining
  model-output/generated-file and terminal compositions retain their original
  atomicity while awaiting their assigned repository extraction.
- Independent read-only review of all 17 changed files found no issues. The
  reviewer independently ran 31 focused cases and verified pure projection
  equivalence and removed-symbol absence.
- Design delta: `None`. No new cross-I/O lock or product mechanism.
