---
title: "Transaction Ownership Phase 31: Worker Session and Stop"
created: 2026-10-02
tags: [backend, worker, architecture, database]
---

# Phase Execution Plan

- Phase: `31, complete Worker Session/Stop, snapshot, projection and recovery boundaries`.
- Branch/base: `refactor/transaction-ownership-261002-19-worker-session-stop` ->
  `main`, requester-merged parent #2057 at `602b1720e`.
  Initial implementation parent `cd4df4362` passed 38 checks with three skipped,
  none failed or unfinished. Git verified that `602b1720e` contains `cd4df4362`
  and both have exactly tree `95dbadd1b4a3d20ff8301c8143df690677997eab`;
  root fast-forwarded the local phase branch after all owner handoffs and verified
  all 34 dirty/untracked file hashes were preserved. No Agent GitHub merge was
  performed.
- Inputs: Phase 27 terminal/Mailbox and Phase 28 Event/tool-result compositions,
  current SessionExecution and Run query primitives, Worker owner lock ordering,
  existing snapshot/error/command and external broker/live-store contracts.
- PR boundary: 24 factory contexts across six Worker modules: lifecycle 17,
  UserStop finalizer 2, canonical snapshot 1, live projector 2, recovery 1,
  runner pending-command 1. Two lifecycle contexts are dormant and removed.
  Factory count is not the number of distinct business operations.
- Deliverables: concrete completed Worker repositories, session-free lifecycle /
  Stop / snapshot / projection / recovery / pending-command orchestration,
  removal of generic application DB callbacks and dormant wrappers, canonical
  errors/DTO defining imports and required caller/fixture integration.
- Non-goals: the Executor's 17 larger database contexts, unrelated Runtime/Chat/
  Settings/Memory ownership, provider work, public Event/API/schema changes,
  new owner/Stop/retry/replay/lock/coordination policies or compatibility wrappers.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through ADR-D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current Agent Execution Loop and Conversation/Event Specs.
- Design delta: `None`.

## Ownership and Shared Contracts

| Workstream | Owner | Owned paths | Dependencies/output | Validation |
| --- | --- | --- | --- | --- |
| Session/lifecycle, snapshot, recovery and command ownership | `/root/tx-engine-input` | worker/session/lifecycle.py and tests; execution_snapshot.py; recovery.py; runner.py and runner_factory.py; canonical Worker guard/Session operation/snapshot/recovery repository modules and worker_session_test.py; canonical WorkDrift error definition/imports; worker/run/executor.py/tests mandatory wiring only | 20 candidate contexts, two dormant removals; completed lifecycle calls and same Worker in-session guard for Stop/remaining quota composition; no raw repositories exported through lifecycle | Owner takeover/missing/stale identity, tree/Session lock order, command equality, pending/activation drift rollback, parent-result/terminal atomicity, snapshot and broker closure |
| User Stop separated database stages | `/root/tx-chat-inventory` | worker/session/user_stop_finalizer.py/tests; new User Stop database repository/input/result/tests; defining imports for moved UserStopDurableEvents where required | Two factory contexts and three generic callback sites become explicit completed partial, cancelled result, marker and clear actions. Uses the shared Worker repository guard internally, never a service or nested completed guard | Separate-commit preservation, idempotent external IDs, active-call ownership, missing Run/error behavior, marker pair rollback, cancellation, post-commit dispatch/clear order |
| Live projection authority reads | `/root/tx-platform-inventory` | worker/live/event_projector.py/tests; new completed projection authority repository/tests | Two completed PostgreSQL reads return detached authority before Redis/store/broadcast work. Keeps exact local active-ID and durable current-Run predicates | Stale/missing suppression, restart/takeover/eviction, all external calls after SQL closure, transparent cancellation and existing best-effort errors |
| Recovery/snapshot read and orchestration tests | `/root/tx-chat-inventory` after frozen Stop handoff | worker/session/recovery_test.py; new repos/worker_session_recovery_test.py and repos/worker_session_snapshot_test.py only | Lifecycle owner explicitly relinquished these three test paths before reassignment; production ownership and 24-context phase scope remain unchanged | Replace empty Session adapters with completed operations; actual PostgreSQL threshold/order/DTO/snapshot/error checks and external closure |
| Integration, shared Worker fixtures and delivery | `/root` | worker/worker_test.py required constructors/imports; phase/master plans, related Specs, integration fixes; global QA/review/PR/CI | Root owns shared fixture integration to avoid concurrent edits; implementation owners supply explicit constructor contracts | Root focused/full tests, type checks, schema equality, all removed interfaces/callers, same retained reviewer and exact-head CI |

- Share one exact Worker repository owner-guard contract. Suggested local name:
  `WorkerSessionOperationRepository.assert_owner_generation_in_session(session,
  session_id=..., owner_generation=...)`. Repository compositions use that narrow
  primitive inside their own transaction; applications never receive the Session.
- Missing Worker Session retains `ValueError("AgentSession not found")`; stale
  generation retains `CanonicalExecutionOwnerGenerationStaleError`; snapshot
  identity failures retain `CanonicalExecutionSnapshotError`. A generic existing
  OwnerBoundSessionManager maps missing and stale alike and is not a replacement
  for the Worker-specific guard. No new failure/authorization policy is introduced.
- WorkDrift and other actually moved errors/DTOs have one canonical defining module
  accessible to repository composition. Update all caller imports, including
  existing worker snapshot re-exports, without aliases or service/Worker imports
  from new repositories. Move only the necessary shared definitions.
- Stop and projection owners receive the lifecycle owner's constructor/guard names
  before wiring. Do not edit peer source or root-owned worker_test.py. Report all
  affected shared fixture fields for root integration. Owners do not stage, commit,
  switch branches, open PRs or run global formatting/pre-commit while peers edit.
- After the Stop 35-case and projection 34-case handoffs were frozen, root
  reassigned only the three recovery/snapshot test paths above with the lifecycle
  owner's explicit non-overlap confirmation. Lifecycle retains its own completed-
  operation fixture cleanup and Worker guard/rollback/two-connection tests.
  This is execution decomposition within M1-M5; Design delta remains `None`.

## Preserved Atomicity and External Effects

- Existing execution admission locks remain ordered: root SessionAgent gate,
  sorted Agents and sorted source/root/direct-parent Sessions. Failed NOWAIT
  savepoint release and the existing narrow contention/claim retry remain intact;
  no retry or lock is added to terminal composition.
- Complete claim/current-owner operations before broker TTL renewal, release,
  activity or publication. ENQUEUED parent-result authority resolves a detached
  parent Session ID before external notification.
- Guarded pending commands compare the same five fields and clear only the exact
  command identity. Idle admission checks pending command, WAKE_SESSION mailbox
  and active Run before its write in one transaction; queue-only input does not
  block idle. Preserve WorkDrift and missing/mismatch outcomes.
- Recoverable selection, pending claim and pending create/input association retain
  their original atomic groups and commit boundaries. A later drift rolls back
  any prior claim in that operation. Activation profile/Session identity/phase,
  cancellation terminal+parent admission, and bridge terminal+suppression retain
  atomicity; bridge gains no ordinary foreground settlement.
- Bulk/conditional terminal/Stop mutations and parent finalization remain one
  transaction with the same Run/Session/owner checks. Retry update retains its
  exact Run-existence/Session guard and ValueError behavior.
- Canonical snapshot remains the existing unlocked durable projection after the
  ownership claim: Session/Agent/Workspace/tree/context/lineage/run state,
  archived started-continuation, command/recoverable/idle validation are unchanged.
- Projector authority reads close before volatile owner advancement, reset,
  eviction, partial/store operations and broadcast. Missing/mismatched ownership
  suppresses work as before. Keep local active-ID and durable None-or-same-ID
  terminal predicates without stronger new final checks. Existing cancellation
  and best-effort publication policies remain unchanged.
- Recovery scan closes before per-record mark/send and retains threshold, limit,
  order and per-record failure behavior. Runner preserves COMPLETE command and
  mailbox-follow-up predicates without changing scheduling policy.

### User Stop has distinct commits

Keep the existing sequence rather than collapse it into a universal transaction:

1. Flush/read live state outside SQL.
2. Admit eligible partials in one external-ID-idempotent transaction.
3. Admit deduplicated cancelled active-call results in another transaction.
4. Remove live projections and replace active-tool projection outside SQL.
5. Mark the Run STOPPED and finalize parent result atomically; notify afterward.
6. Append the interrupted Event and Run marker together; dispatch afterward.
7. Clear the guarded Stop request in a later completed transaction.

The no-effective-Run branch bulk-terminalizes/notifies without fabricated markers.
The durable running Run owns active tool calls; passed or Redis-only calls do not
become authority. Skip empty partial/call actions; active calls without a Run keep
the current RuntimeError. `record_interrupted_run` retains its own dispatch/clear
order and does not gain parent notification. Every database action uses the same
Worker generation guard. Cancelled results reuse EngineToolResultOperationRepository
`finalize_in_session`, not a nested completed transaction. Earlier committed stages
survive later failures; marker pairs roll back together and Stop clear stays last.

## Mandatory Executor Interface Closure / Explicit Residual

- `_advance_model_operation_after_quota` has one live Session consumer of lifecycle
  `assert_owner_generation`. Rewire to the same Worker repository in-session guard
  in that existing quota transaction; do not nest a completed operation.
- Eleven Executor borrows of lifecycle.agent_run_repository (WaitToolkit DI and
  quota/main-turn/compaction query calls) become an explicitly required injected
  AgentRunRepository. Update `_run_executor` / `_executor` fixtures and its direct
  test references. Lifecycle service must not export a raw query repository.
- These narrow changes close removed interfaces. They do not migrate or exclude
  any of the Executor's 17 database contexts, which remain a subsequent batch.

## Removal and Absence

- Remove lifecycle `run_short_db`, its ten local callback sites and all service
  session helpers/manager/query injection; Stop's `_run_short_db` and three local
  callbacks; all six assigned application factory lifetimes.
- Remove scoped dormant lifecycle `set_inference_state` and
  `associate_agent_run_input_events`, plus uncalled
  `mark_session_running_for_input_wakeup`; the identically named live narrow
  AgentSessionRepository methods remain. Remove the uncalled Stop wrapper
  `_mark_session_agent_runs_terminal`, preserving the live finalize path.
- Root reconfirms source/test/CLI constructor, call, attribute and import absence;
  static name absence is not evidence of all dynamic behavior. Replace no-op
  Session fixtures with explicit operation wiring and real PostgreSQL boundary
  evidence rather than preserving the old ownership interface in adapters.
- Keep completed repository primitives needed by other atomic compositions and
  explicitly residual Executor contexts. No schema, provider/Event format,
  configuration, migration, retry or durable lifecycle removal is authorized.

## Validation and Delivery

- Capture generated public/admin OpenAPI before edits and require exact equality
  after integration. Internal Worker ownership adds no public contract/client work.
- Focus existing lifecycle/Stop/projector/recovery/Worker/Executor owner/takeover,
  snapshot/repository, terminal-finalization and tool-result suites.
- Add real PostgreSQL guard/lock takeover and missing/stale/snapshot error cases;
  use independent sessions and deterministic barriers for contention, not sleeps.
  Shared savepoint fixtures cannot prove two-connection blocking.
- Inject failure after pending claim/activation/profile association, parent enqueue,
  marker first write and tool-result append to prove each original group rolls back.
  Test Stop branch/multiple stage failures, repeat/empty/live-only calls, provider
  races, idempotency, cancellation and non-replayability.
- External collaborators assert no open transaction/context before broker/live
  store/broadcast/dispatch work, on successful, read, error and cancellation paths.
- Root owns integrated focused/full backend pytest, ty --error-on-warning,
  Ruff/format, pre-commit, defining imports/removed names, residual inventory and
  equivalent OpenAPI. Save commands, logs, exits and exact skip reasons.
- Single retained reviewer: `/root/phase25-independent-review`, read-only on the
  stable integrated phase diff after root validation; root handles corrections
  and material targeted re-review under the established criteria.
- Create the phase PR against fresh main after the requester-merged #2057.
  Check applicable required E2E and normalized exact-head CI.
  Never merge without explicit requester authorization. Keep broader work active.

## Context Checkpoint and Scope Drift

- Root reconfirmed current source counts `17/2/1/2/1/1` = `24`; the six Worker
  files are identical between inspected parent 574 and current cd4 (prior changes
  were Settings and upstream OAuth, not Worker implementation).
- Initial comparable whole candidate inventory: 556 / 103 files, not confirmed
  violation count. Expected bounded delta is 24; verify rather than extrapolate.
  Other services, Runtime, API/Scheduler and Executor 17 remain named residuals.
- Phase 30 parent passed latest-main backend 7201 cases (three existing Redis-only
  memory variants), type/pre-commit/OpenAPI gates and exact-head CI 38/3 with no
  failures/pending. Independent 37-path review had no findings and 87 cases passed.
- No new product, error, authorization, broker, projection, lock, retry, replay,
  schema, default or fallback mechanism. Design delta: None.
- Implementation, root integrated validation and independent review complete;
  PR/CI pending. Broader issue coverage and final spec promotion remain open.

## Root Integration Checkpoint

- All production and test owners handed off frozen work, including the explicitly
  reassigned recovery/snapshot test segment. Root integrated the required shared
  Worker constructors and canonical error imports without compatibility aliases.
- The 24 assigned application factory contexts are absent. The old generic
  lifecycle/Stop callbacks, dormant helpers, snapshot error re-exports, lifecycle
  raw-repository borrows, and no-op ownership-shaped test adapters are absent.
  Narrow live query primitives remain; the Executor's 17 contexts are residual.
- Comparable candidate inventory: 556/103 -> 532/97 (contexts/files), including
  services 482, Worker 17, Runtime 16, API 9, Scheduler 7 and one test fixture.
  These are lexical candidates, not verified remaining violations or issue closure.
- Root focused regression: 385 passed, no skips. Full backend: 7,311 passed,
  three existing Redis-specific contract variants skipped on the memory backend,
  six dependency/test-fixture warnings. No required test failed.
- Exact skips: one Runtime coordination retention contract and two Runtime
  terminal-coordination stale-index variants. Optional provider credentials were
  not needed; PostgreSQL locking tests used genuine independent connections.
- Root changed-path Ruff/format (31 Python paths), whole backend
  `ty --error-on-warning`, pre-commit, documentation validation and whitespace
  checks passed. Public/admin generated OpenAPI remains exactly equal at 234/69
  paths; no client or schema change is required.
- Current Agent Execution Loop Spec v202 records the bounded completed operations
  and separated Stop stages. Other matched Specs retain their existing product
  contracts. Snapshot-wide `implemented` markers and plan cleanup remain deferred
  until the broader Requirements are fully satisfied.
- Existing lock order, narrow claim retry/savepoint semantics, explicit commits,
  cancellation and rollback, Worker missing/stale/snapshot errors and external
  effect order are preserved. No new cross-I/O lock or material mechanism was
  introduced; the Phase 31 exception ledger is `None`.
- The same read-only reviewer `/root/phase25-independent-review` covered all
  34 paths (four import-only AST comparisons and 30 direct reviews), found no
  findings and independently passed the same 385-case focused suite. Final patch,
  index and file freeze checks passed; no implementation correction was needed.
- Remaining phase gates: PR creation against main and applicable exact-head CI.
  No autonomous merge or issue closure.
