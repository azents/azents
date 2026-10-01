---
title: "Transaction Ownership Phase 14: Engine Reads"
created: 2026-10-01
tags: [backend, engine, architecture, database]
---

# Phase Execution Plan

- Phase: `14, Engine completed operations`
- Branch/base: `refactor/transaction-ownership-261001-2-engine-reads` →
  `refactor/transaction-ownership-261001-1-runtime-engine`
- PR boundary: replace the residual Engine-owned database contexts in
  `engine/run/resolve.py` and `engine/events/engine_adapter.py` with typed completed
  repository operations.
- Inputs: Phase 13 Runtime Control read operations and the approved
  `transaction-260908` Requirements, ADR, and Design revision 1.
- Deliverables: completed model/Agent/integration snapshots, effective Toolkit
  reads, system-error append, compaction transcript preparation, initial
  user-message/Run preparation, and polled user-message append.
- Non-goals: model selection policy, transcript content or ordering, compaction
  behavior, Toolkit visibility, provider calls, schema/API/protocol/configuration,
  retry/fallback behavior, or cross-I/O locks.
- Interfaces: existing `ResolveError`, `RunRequest`, Event transcript,
  AgentSession owner-generation fence, AgentRun activation, and Toolkit binding
  contracts remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`,
  `transaction-260908/ADR-D1` through `ADR-D3`, and
  `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove Engine application-owned transaction contexts for
  the bounded operations while retaining database-only repository composition.
- Absence verification: search the changed Engine modules for direct
  `session_manager()` and `owner_session_manager()` contexts and verify that the
  completed repositories import no services or external collaborators.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Resolve reads | `/root` | `engine/run/resolve.py`, `repos/engine_read.py`, focused tests | Existing Agent, integration, and Toolkit repositories | Detached atomic model-source snapshots and completed individual reads | Resolve and repository tests; transaction-closure assertions |
| Event operations | `/root` | `engine/events/engine_adapter.py`, `repos/engine_event_operation.py`, focused tests | Existing transcript, Session, Run, and owner-generation repositories | Completed transcript preparation and append operations | Adapter and repository tests; stale-owner coverage |
| Integration and evidence | `/root` | Phase plan and changed Specs if required | Both implementation workstreams | Stable integrated diff and phase checkpoint | Ruff, format, `ty`, focused pytest, pre-commit, independent review |

- Integration order: add typed repository operations and tests, replace Resolve
  contexts, replace Event adapter contexts, then run the integrated validation
  matrix.
- Independent review: `/root/issue-hardening-review` performs one read-only review
  after every implementation workstream is complete and the integrated diff is
  stable.
- Final validation: root runs changed-path Ruff and format, full backend `ty`,
  focused Resolve/adapter/repository tests, pre-commit, context/import searches,
  and creates the stacked PR.
- Scope-drift check: confirm all bounded contexts are removed, no approved behavior
  is omitted, and no lock, queue, retry, fallback, schema, API, protocol, or
  configuration mechanism is added.
- Context checkpoint: Phase 13 is open as PR #2005 with independent review findings
  at zero. Phase 14 preserves the existing atomic groups and owner-generation
  fences; provider/OAuth/model/hook/polling/compaction generation work remains
  outside repository transactions. Remaining scope starts with Agent service
  operations after this PR opens.
