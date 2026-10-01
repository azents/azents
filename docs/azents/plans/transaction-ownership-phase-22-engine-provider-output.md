---
title: "Transaction Ownership Phase 22: Engine Provider Output"
created: 2026-10-01
tags: [backend, engine, provider-output, files, architecture, database]
---

# Phase Execution Plan

- Phase: `22, Engine provider-output metadata boundaries`
- Branch/base: `refactor/transaction-ownership-261001-10-engine-execution-output`
  → `main` at `ed2a41fb3` after PR #2019 merged with required CI passed.
- PR boundary: replace the three Provider Output caller-owned read transactions
  with typed completed repository operations while retaining the existing
  caller-composed metadata admission transaction used by model/tool Event commit.
- Inputs: Phase 21 Scheduled/Subagent operations, PR #2019, and the bounded
  23-context/3-file Engine direct-literal checkpoint.
- Deliverables: completed provider-output authority/retry preflight, completed
  cleanup protection read, completed scope validation, unchanged final metadata
  admission composition, and an updated Engine residual checkpoint.
- Non-goals: `events/execution.py` transaction ownership, compaction/filter
  ownership, object-storage provider changes, file schemas, retry policy,
  compensation policy, public APIs, or new locking mechanisms.
- Interfaces: deterministic output identity, Session/Run/owner authority,
  retention-root fencing, retry object preservation, metadata identity
  collision checks, upload-before-admission ordering, cleanup compensation,
  cancellation, and error messages remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`,
  `transaction-260908/ADR-D1` through `ADR-D3`, and
  `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove direct session-manager and low-level repository
  access from `engine/events/provider_output.py`; repository operations receive
  no service, S3, provider, Engine orchestration callback, or arbitrary callback
  dependency.
- Absence verification: assigned direct-session search, repository-to-service
  import search, retry/cleanup/admission regressions, transaction-closure tests,
  and storage-I/O-active-transaction sentinels.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Provider output persistence operations | `/root` | provider-output operation repository/data/tests | file authority, AgentRun, ExchangeFile, ModelFile repositories | Completed scope/preflight/cleanup reads plus database-only in-session admission | repository boundary and identity tests |
| Engine materializer migration | `/root` | `engine/events/provider_output.py`, adapter composition, tests | operation repository, existing S3/config services | Upload/delete remain transaction-free; materializer no longer owns sessions or narrow repositories | provider-output and execution tests |
| Engine residual checkpoint | `/root` | phase/master plans and bounded inventory evidence | assigned workstreams | corrected remaining Engine classification | direct-session/import searches |

- Integration order: define repository-owned metadata contracts, migrate
  preflight and cleanup reads, migrate in-session metadata admission, wire the
  adapter dependency, remove exposed low-level service dependencies when no
  longer needed, update Specs, then run the residual checkpoint.
- Independent review: one read-only reviewer inspects authority, deterministic
  identity, retry preservation, cleanup compensation, and transaction closure.
- Final validation: root runs changed-path Ruff/format, focused provider-output
  and execution pytest, full backend `ty`, full backend pytest, pre-commit,
  direct-session/import searches, and creates the next stacked PR.
- Scope-drift check: preserve storage keys, hashes, metadata, lock behavior,
  errors, retry reuse, compensation, and cancellation; add no lock, queue,
  retry, fallback, API, schema, protocol, dependency, or configuration mechanism.
- Context checkpoint: this phase owns all three direct session contexts in
  `provider_output.py`. Execution and compaction/filter ownership remain later
  batches.

## Implementation Checkpoint

- `ProviderOutputOperationRepository` owns completed scope validation,
  retry-metadata preflight, and cleanup-protection reads. The same repository
  retains the database-only in-session metadata admission used by the atomic
  model/tool Event transaction.
- `ProviderOutputMaterializer` no longer opens sessions or reaches through
  services to narrow repositories. S3 upload and compensation delete remain
  outside database transactions, and repository errors retain the existing
  model-visible messages.
- Deterministic ExchangeFile/preview/ModelFile identity validation, retention
  root fencing, owner-generation authority, committed retry preservation, and
  rollback compensation remain unchanged.
- Assigned `provider_output.py` direct session contexts are zero; the new
  operation repository imports no service, S3, provider, or arbitrary callback
  surface.
- Focused provider-output/execution/adapter validation: 123 tests passed.
  Full backend validation: 6,824 tests passed and 3 skipped. Full backend
  `ty --error-on-warning` and repository-wide pre-commit passed.
- Independent reviewer `/root/phase22-review` reported zero findings after
  checking authority, deterministic identity, retry preservation, compensation,
  atomic admission, S3 boundaries, DI, and Spec alignment.
- A bounded post-change direct-literal scan finds 20 remaining Engine
  session-manager contexts: 18 in `events/execution.py` and 2 in
  `events/filters.py`. These remain later execution and compaction phases.
- Design delta: `None`.
