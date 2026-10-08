---
title: "Transaction Ownership Phase 28: Complete Event Engine Execution"
created: 2026-10-02
tags: [backend, engine, worker, architecture, database]
---

# Phase Execution Plan

- Phase: `28, complete assigned Event Engine output and finalization ownership`.
- Branch/base: `refactor/transaction-ownership-261002-16-engine-execution-completion`
  → `main` at `4a530cb1d` after the requester merged PRs #2049/#2050 with
  passing normalized CI checks. Initial implementation/review base `392e24b84`
  is an ancestor of that main and has the identical source tree. No Agent merge
  was performed. The Historical Memory integration baseline is `cf881e8c5`.
- PR boundary: replace all eleven remaining AgentRunExecution DB contexts with
  completed input/phase/result/output/finalization operations and replace the
  Worker failed-run transaction with one completed failure operation.
- Inputs: Phase 27 canonical terminal/Mailbox compositions; existing provider
  metadata authority, model-operation completion, owner-bound session manager,
  transcript and Run query primitives. The inspected upstream main delta makes
  no changes to the assigned execution/provider/contract/executor/finalizer paths.
- Deliverables: zero direct sessions or SQLAlchemy/session-taking interfaces in
  execution.py; typed metadata admission instead of prepared persist callbacks;
  existing completion DTO instead of the RunContext DB callback; canonical
  failure repository and session-free Worker failure orchestration.
- Non-goals: unrelated Worker executor/lifecycle scopes, broader Engine Tool and
  resolve paths, Mailbox/Chat/Platform ownership, the new Memory scopes, public
  APIs, schemas, delivery/retry policy, provider protocols, configuration, locks.
- Interfaces: preserve each existing atomic group, owner/version/probe fences,
  deterministic Event identities, phase/marker/snapshot/retry semantics, native
  Event serialization, terminal status/pin behavior, error classes, cancellation,
  tool barrier extent, cleanup acknowledgement and publication order.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through ADR-D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current Agent Execution Loop and Context Compaction Specs.
- Design delta: `None`.
- Removal obligations: application execution scopes, raw query/session assembly
  dependencies on execution, its session-taking helpers/protocols; prepared
  output persist(session) and materializer persist; RunContext completion callback
  and obsolete Worker completion helpers; Engine failed Event-store module and
  Worker failure scope; lifecycle claim helper after its final caller migrates.
  Update every defining-module caller with no aliases or compatibility re-exports.
- Absence verification: direct-context/import/interface/caller searches, real
  owner takeover tests, explicit transaction closure/rollback tests and external
  collaborator ordering tests. Execution endpoint is zero, not another partial
  one-context milestone; unrelated repository-wide residuals remain visible.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Engine output and terminal operations | `/root/tx-engine-input` | execution.py/tests, ownership_test.py, engine_adapter.py/tests, provider_output.py/tests, engine/run/contracts.py, worker/run/executor.py/tests; new output/finalization/mutation repository modules/tests; provider_output_operation.py metadata DTO; canonical pure terminal Event projection | Phase 27 and existing metadata/completion repositories | completed typed operation dependencies and zero execution sessions | metadata/Events/snapshot/retry/active-call atomicity, terminal settlement, no-I/O boundaries, owner takeover, lost acknowledgement |
| Failed-run atomic ownership | `/root/tx-runtime-inventory` | new failure repository/input/result/tests; engine/events/finalization.py/tests removal; worker/run/finalizer.py/tests; worker/session/lifecycle.py/tests only claim helper removal | Phase 27 terminal repo and owned Session primitives | completed Stop-claim/failure Events/terminal delivery with external dispatch afterward | Stop precedence, missing/stale error types, terminal slot invariant, rollback/cancellation, dispatch order |
| Integration and documentation | `/root` | phase/master plans, Agent Execution Loop/Context Compaction Specs, integration fixes | both stable workstreams | full validation checkpoint and PR | root-owned focused/full pytest, ty/pre-commit, same independent reviewer, CI |

- Shared contracts: new repository dependencies are required explicit completed
  operation objects; preserve existing nullable DB-collaborator semantics only
  where previously supported, with every caller supplying its value. Do not
  introduce generic finalize flags, arbitrary callbacks, Session aliases or
  materializer/Worker objects inside repositories. Cross-workstream files do not
  overlap; root coordinates any shared constructor registry correction.
- Integration order: canonical detached metadata/terminal projection data;
  database-only Event helpers and output/terminal operations; Engine prepared and
  execution/adapter/context wiring; independent failure operation and Worker
  dispatch migration; old interface removal; root docs and validation.
- Atomic groups: model output metadata + Events + usage marker + prompt snapshot
  replacement/deletion + retry clear + active-call phase share one transaction.
  Normal terminal completion remains a separate later transaction, with marker,
  foreground settlement, terminal delivery and pin release. Client metadata and
  canonical result admission share one transaction. Failed Run Stop claim,
  failure Events and terminal delivery also share one transaction.
- Fixed branch distinctions: foreground success is composed only into normal
  model completion, last tool-turn completion and committed scheduled-result
  recovery. Early stop, polled/bridge completion, conditional tool interruption,
  turn-limit interruption and partial-stream interruption retain their original
  marker/settlement/publication differences. Marker/prelock ordering is unchanged.
- External-effect boundary: upload/decode/preview preparation and compensation
  remain outside DB work. Tool barrier runs completed output admission and then
  post-commit phase publication before acknowledging prepared output admission.
  Post-commit publication failure still performs protected cleanup. Translate only
  ProviderOutputOperationError into the existing ModelCallError at the closed
  Engine boundary. Provider, tool, Runtime, broker and output callbacks never
  receive a live session or enter a repository.
- Failure boundary: use the same owned Session lock, missing/stale exceptions
  and durable Stop predicate; preserve mark_terminal_if_running and safe metadata.
  Dispatch error Event, marker and RunComplete after commit in the existing order.
  Do not add pin release, retry/outbox or cleanup policy to failed finalization.
- Independent review: `/root/phase25-independent-review`, read-only, requested by
  root for the complete stable integrated diff after validation.
- Final validation: root focused operation/execution/provider/ownership/adapter/
  completion/compaction/failure/Worker suites; supported lowerer regressions;
  full backend pytest and ty --error-on-warning; pre-commit; removed-interface and
  import/caller checks; applicable required PR E2E and CI. Use explicit saved exits.
- Scope-drift check: no product, schema, dependency, provider, retry, fallback,
  queue, configuration, new fence or locking mechanism. Preserve existing
  two-transaction output/completion split rather than coalescing it.
- Context checkpoint: baseline execution owns nine terminal and two output
  contexts. Worker failure owns one extra context; obsolete completion wrappers
  have no production callers and are removed rather than retained as dormant
  session-taking helpers. Adapter DI composition opens no sessions and is
  explicitly classified as wiring, not a corrected/excluded transaction by proxy.
  No repository-wide completion is claimed while other owned areas remain.

## Implementation and Validation Checkpoint

- Execution now receives five explicit completed repositories and typed model
  completion data. Its eleven direct scopes, SQLAlchemy/session interfaces,
  raw query constructor dependencies, and session-taking mutation helpers are
  absent. The adapter retains only its non-transactional DI assembly role.
- Output admission consumes detached metadata authority/create records. Prepared
  objects and the materializer expose no persist(session) path. Tool barrier,
  publication, admission acknowledgement and protected cleanup order is retained.
- Typed foreground completion replaces the RunContext callback and Worker
  closure/session helpers; compaction settlement uses the same existing typed
  authority and direct COMPACTION repository mutation.
- Failed Run finalization owns Stop/generation admission and failure output in
  one completed operation. Worker performs only post-commit dispatch. The old
  Engine Event-store module and lifecycle claim helper are removed.
- Root integrated focused suite: `296 passed`. Root full backend suite:
  `6984 passed, 3 skipped`. The skips remain memory variants of Redis-specific
  retention/stale-index contracts, not missing live prerequisites.
- Full backend ty, full pre-commit, diff checks, and removed-production-interface
  searches passed with explicit zero exit markers. The initial focused command
  referenced an absent dedicated model-operation test file and failed before
  collection; the corrected suite uses the actual model-candidate health path.
- Implementation-owner evidence separately includes 209 existing Engine cases,
  42 new output/terminal cases, and 43 failure/owner cases. Test-only explicit
  fixture assembly preserves recording queries and real owner-bound repositories
  without a production compatibility wrapper.
- Latest strict candidate inventory is 599 contexts in 111 files, down from 612
  at the Phase 27 checkpoint: eleven Engine contexts, one failed-Run Worker scope,
  and one unused completion wrapper are removed. This is discovery evidence,
  not a repository-wide violation count or closure claim.
- Independent read-only review of all 30 changed files found no issues; the
  reviewer independently passed 122 operation/Worker/execution/owner-takeover
  cases and verified pure terminal projection equivalence. No late source or
  test correction invalidated root's completed validation.
- Design delta: `None`; no added lock, fence, policy, schema, retry or fallback.
