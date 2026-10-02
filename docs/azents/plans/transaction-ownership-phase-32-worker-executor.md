---
title: "Transaction Ownership Phase 32: Worker Executor"
created: 2026-10-02
tags: [backend, worker, engine, architecture, database]
---

# Phase Execution Plan

- Phase: `32, complete Worker Executor, local metadata and Wait read boundaries`.
- Branch/base: `refactor/transaction-ownership-261002-20-worker-executor` ->
  `refactor/transaction-ownership-261002-19-worker-session-stop`, parent PR #2058
  head `e14bf1de822ce06e776d431a0ac830ea252f10ce`. Reconcile with main if the
  requester merges the parent; never merge autonomously.
- Start gate: Phase 31 PR exists and root implementation/review gates passed.
  Parent exact-head CI is now confirmed: 38 passed, two path-condition skips,
  no failed/pending checks, MERGEABLE/CLEAN. Phase 32 implementation may start.
- Inputs: Phase 31 completed Worker owner guard, canonical errors/snapshots,
  lifecycle/Stop/projection operations; existing completed Engine read repositories,
  frozen model-operation/health/reservation primitives and Mailbox operations.
- PR boundary: 21 existing factory contexts: Executor 17 (11 read/projection and
  six coherent model/profile contexts), ModelMetadataService.capture one and
  AgentWaitService.observe one, and Kimi runtime success/failure persistence two.
  The adjacent reads and required token dependency closure are explicitly
  included, not silently excluded. No context is an empty/no-query exemption.
- Deliverables: completed domain reads/model operations; session-free Executor,
  Metadata, Wait and Kimi runtime persistence orchestration; canonical shared selector/data definitions;
  explicit completed Engine resolve dependencies rather than factory propagation;
  all required production/fixture callers and genuine PostgreSQL failure evidence.
- Non-goals: changes to profile/candidate/provider/quota/lease/Stop/replay policy,
  stronger authority predicates, new locks/retries/coordination, public/schema/API,
  Runtime behavior, successful-settlement rules, unrelated service transactions,
  or compatibility wrappers. No material blocker was found in bounded discovery.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current Agent Execution Loop, Run Resume, Toolkit, Conversation and
  model-metadata contracts.
- Design delta: `None`.

## Ownership and Required Interfaces

| Workstream | Owner | Owned paths | Dependency/output | Validation |
| --- | --- | --- | --- | --- |
| Model operations and complete Executor integration | `/root/tx-engine-input` | worker/run/executor.py and executor_test.py exclusively; new Worker model operation repository/data and pure normalization/error definitions; shared selector canonical relocation; narrow defining imports in repos/session_title and repos/historical_memory plus selector patch targets | Own six model/profile contexts and all Executor integration of peer read/resolve contracts, constructor/import closure and existing orchestration cases; shared model repository contracts published before PG tests | Failure commit vs exception rollback, reservation/health/slot atomicity, exact fences/lock order/three attempts, preserved old cases and no fake-SQL ownership adapter |
| Read/projection, Wait/Metadata and Engine resolve dependencies | `/root/tx-platform-inventory` | new Worker Executor read repository/data/tests; services/agent_wait.py and model_metadata.py/tests and new composing repositories/data/tests; engine/run/resolve.py/tests and actual resolve callers except Executor/tests and selector-consumer repositories owned by the model owner; narrow removal of Session-taking Git Worktree projection helper; canonical metadata source key imports where required | Own 11 Executor reads plus two adjacent contexts; send completed read/Wait/Metadata/resolve signatures to Executor owner immediately; never edit Executor or its test file | Same predicates/routing/fallback/order; SQL scopes close before mailbox/provider/runtime/dispatch; canonical definitions and factory caller closure |
| Genuine model-operation PostgreSQL regression | `/root/tx-chat-inventory` | new model-operation repository test modules and shared PG fixture helpers scoped to those tests only | Consume stable model repo input/result/constructor contracts; no production or Executor fixture edits | Actual partial writes and claims, normal Failure commit, compaction exception rollback, stale fences, cancellation, health/reservation identity and external closure |
| Integration and delivery | `/root` | shared worker/worker_test.py only if a defining import actually moves; phase/master plans and related Specs; integration corrections and global QA | Root controls all scope/contract decisions, stable merge of owner handoffs, same reviewer and PR/CI; no concurrent owner staging/branch operations | Full backend/type/Ruff/format/pre-commit/OpenAPI/removal, immutable freeze, review and exact-head required CI |

- Single source owner for the large Executor and its 76-call test builder avoids
  concurrent function/import/constructor edits. The read owner supplies concrete
  typed completed contracts, not patching peer source or exporting a manager.
- Suggested local completed interfaces: WorkerExecutorReadRepository for the 11
  detached reads and WorkerExecutorModelOperationRepository for the six exact
  database groups. Names/layout are local details, not new Design authority.
- Model/profile failure DTOs, normalization and ProfileResolutionRuntimeError have
  one repository-safe actual defining module. Keep assembled RunRequest/provider
  materializers in application orchestration. No repository imports Worker/service
  definitions or arbitrary application callbacks.
- Existing EngineInvokeReadRepository, EngineModelReadRepository and
  EngineToolkitReadRepository are already completed operations. Replace the ten
  Executor factory passes and resolve helper construction with required injected
  concrete dependencies, updating all actual callers. Never borrow/export a new
  operation repository's session_manager or hide the factory under an alias.
- Shared select_model_operation_candidate and private transfer helper move to one
  canonical database-only composition module. Update all eight production sites
  (four current Executor sites become model-repository composition; two Session
  Title and two Historical Memory repository sites retain their current atomic
  scopes) plus test patch targets. No broader Title/Memory behavior rewrite.
- Wait retains the initial all-kind mailbox check before its descendant snapshot,
  and per-descendant wake mailbox checks after closure. Preserve current missing
  Session behavior, descendant order/count and active-path predicate exactly.
- Metadata captures only the selected local validated source. Preserve the
  saved-capability-maximum skip, missing source, lookup and maximum behavior;
  source/provider fetching is not added. Move only shared pure keys/DTOs needed
  to avoid repository-to-service imports, updating actual defining callers.
- Concrete resolve closure found Kimi's two persistence scopes after the initial
  19-context report. Root read the complete implementation and included this
  required dependency within M1-M5. The read owner owns Kimi runtime/repository/
  tests and actual ensure/refresh callers except the Executor/selector consumer
  files owned by the model owner. Keep HTTP outside both completed operations,
  the existing FOR UPDATE plus secrets-equality fence, missing/concurrent refresh
  outcomes, status and failure mappings, five-minute threshold and 20-second HTTP
  limit. No new config fence, token/provider policy, retry or lock. Move necessary
  pure credential/token/error types canonically instead of importing mixed
  service/client modules into repositories or retaining a manager alias.

## Preserved Model Groups and Failure Outcomes

- Requested profile selection locks Agent then Session and checks their mapping.
  Keep explicit/Session/default precedence, stale-label/source/effort/options
  normalization and empty-option ValueError. No owner guard currently exists in
  this operation; adding one is not authorized.
- Quota starts the existing Worker in-session guard in the same transaction,
  then locks Session and Run. Preserve route/slot equality and exact existing
  errors; do not add an extra Run-Session identity predicate or reject the current
  stale-health settlement differently. Renewal, advancement/selection, reservation
  transfer/clear, slot persistence, retry clearing and model-call-start clearing
  remain atomic. Exhaustion is caught INSIDE and commits its reached changes.
- Fresh preparation keeps unlocked profile snapshot -> locked chain/claim phase
  -> external runtime/input materialization -> fenced inference write. Exactly
  three existing outer attempts remain. Prewrite profile drift or final operation
  ID/cursor drift continue that loop; no new retry or final Agent/version fence.
- Normal Failure returns inside fresh preparation COMMIT the already reached
  profile/health/claim/slot work. Missing Lightweight option after foreground claim
  retains its existing partial committed outcome, not a newly invented rollback
  or cleanup. Foreground/compaction exhaustion and success-only reservation clear
  retain their original reachability and transaction grouping.
- Compaction background selection creates no foreground probe/reservation.
  Selection exhaustion writes then raises ProfileResolutionRuntimeError INSIDE
  the scope, so those writes ROLL BACK. A runtime-resolution failure after a
  successful preparation instead happens after its committed scope. Preserve
  both outcomes and concrete failure codes/messages/types.
- Existing root NOWAIT/savepoint -> ordered Agent -> ordered Session -> Run locks
  and narrow claim contention retry remain. No model/provider operation, Toolkit
  or OAuth/credential call occurs inside these DB operations.
- Stop precedence, bridge transfer, model quota before generic retry budget,
  heartbeat revocation, ordinary cancellation, partial discard and successful
  ModelOperationCompletion settlement are unchanged. Earlier prepared commits
  survive later external failure; no new replay or compensation policy.

## Preserved Eleven Reads

- Agent capability refresh and idle-toolkit Agent read remain unlocked. Keep
  existing missing-Agent capability/version/memory defaults versus the current
  explicit RuntimeError at the separate refresh site.
- Initial recovered Session read retains its ValueErrors; post-invalidated-context
  missing Session retains wake-up and no-actionable-work outcome after closure.
- Runtime execution-mode/memory/capability projection remains pure; later provider
  and Toolkit work is outside the read. Do not strengthen missing-Agent policy.
- Tree notifications retain current/deduplicated/sorted/excluded Session IDs,
  missing SessionAgent suppression and existing per-target best-effort publication.
- Model drift keeps missing/invalid DTO -> True and exact profile/ordinal/settings
  comparison, not new enabled/version/owner checks.
- Action projection uses existing ordered pending/running records; action execution,
  cancellation and publication follow closure. Remove its live-Session service
  helper rather than retaining a borrowed service query inside the new repo.
- Actionable transcript read keeps Session head and non-reverted Event-ID-ordered
  transcript in the same scope; pure last-marker/kind eligibility remains outside.

## Removal, Validation and Delivery

- Remove all 21 assigned application lifetimes, Executor SessionManager/AsyncSession
  and obsolete query collaborators when no longer consumed; shared factory/helper
  interfaces and Session-taking service selector/projection helpers; moved DTO/key
  re-exports and test adapters that only simulate old application-owned SQL.
- Retain narrower in-session query/composition primitives and already-executed
  schema/migrations. No general callback runner, optional constructor fallback,
  dormant manager export or raw-service repository borrowing is acceptable.
- Preserve all existing Executor/resolve/Wait/Metadata behavior tests. Modernize
  the Executor builder and fake-SQL/health adapter surface through completed typed
  operations; do not silently drop cases because signatures changed.
- Add genuine PostgreSQL tests for each model group's reached writes, explicit
  committed failures and rollback exceptions, generation/profile/operation fences,
  reservation transfer/clear and health identities. Independent connections and
  authoritative barriers prove contention; savepoints alone cannot prove it.
- Inject failure/cancellation after actual profile/health/claim/slot/inference
  writes and assert the exact original transaction outcome. Prove external work
  sees zero open contexts/transactions, including read/error/cancel paths, with
  provider/Runtime/Toolkit/mailbox/dispatch collaborators. No live credentials.
- Root validates integrated focused/full backend, whole ty --error-on-warning,
  changed-path Ruff/format, pre-commit, exact generated OpenAPI and schema/client
  equality, constructor/caller/import/manager absence and fresh candidate counts.
  Expected comparable delta is 21, but verify rather than extrapolate; baseline
  532 contexts/97 files is not a verified violation or final coverage count.
- Single retained reviewer `/root/phase25-independent-review` is read-only on the
  whole stable root-integrated diff after ALL handoffs and root validation. Root
  owns grounded corrections and material targeted re-review.
- Create the next stacked PR over #2058 if open, or reconcile requester-merged
  main first. Applicable exact-head required CI/E2E must pass; never merge or close
  #1718 autonomously. Final broader Spec promotion and plan cleanup remain later.

## Context and Scope Checkpoint

- Parent Phase 31: root 385 focused / 7,311 full pass, three existing Redis-specific
  memory-backend contract skips; whole ty/Ruff31/format/pre-commit/OpenAPI234/69
  equality/removal passed. Same reviewer covered 34 paths, no findings, 385
  independent cases passed. PR #2058 head e14bf1de8 has 38 passed checks, two
  unchanged-path Helm/TypeScript skips, no failed/pending checks, MERGEABLE/CLEAN.
- Root post-main fingerprint reconfirmed: Executor SHA256
  9d041865a0de8e1dd2bf00bbe77b0468edac9102f0039650b58dcfe24db9c5d6,
  contexts 17/1/1 exactly plus Kimi persistence two found through resolve closure;
  discovery helper/DTO/caller map is supporting evidence,
  not new approval. Provider/model/lease/Stop policy is fixed by current behavior.
- No confirmed active external overlap or material blocker was found in the 21
  scoped SQL/pure closures. Complete full-repository alias/implicit transaction,
  exclusions and exception coverage remains unfinished outside this batch.
- Scope-drift check: all M1-M5 removal/group/closure duties included; no stronger
  predicate, failure commitment change, retry, lock or framework added. Escalate
  a genuinely material unsupported mechanism rather than silently change behavior.
- Implementation, all owner handoffs, root final QA and independent review
  complete; PR/CI pending. Broader issue coverage remains unfinished.

## Root Integration Checkpoint

- Frozen owner handoffs: model/Executor 102 passed, six-group PostgreSQL 79 passed
  (including five distinct-PID races), read/Wait/Metadata/Kimi/resolve 195 passed.
  These overlapping scoped suites are not summed into a root acceptance count.
- Root integrated focused regression: 624 passed, no skips. Full backend:
  7,419 passed, three existing memory-backend Redis-specific contract skips,
  six dependency/test-fixture warnings, no failed required test.
- Exact skips remain one Runtime coordination retention contract and two terminal
  coordination stale-index variants. No PostgreSQL or new ownership test skipped.
- Root changed-path Ruff/format (48 existing Python paths), whole backend
  `ty --error-on-warning`, pre-commit, documentation/whitespace and scoped
  removal/canonical-import/reverse-import/test-adapter checks passed.
  Generated OpenAPI remains exactly equal: public 234 / admin 69 paths.
- All 21 assigned factories, ten Executor factory passes, mixed selector/error
  imports and ownership-shaped SQL fixture adapters are absent. The selector has
  eight canonical actual consumers. Root's comparable candidate inventory is
  532/97 -> 511/93, with Worker zero direct candidates, services 478, Runtime 16,
  API 9, Scheduler 7 and one infrastructure fixture. This is not global closure.
- Full review target: 53 raw paths / 52 Git changes after selector-file rename
  detection. All production/test file hashes remain owner-frozen; only root
  document checkpoints are updated before independent review.
- Existing fresh normal-failure commits, quota exhaustion commits, compaction
  inside-error rollbacks, exact three attempts/final operation fences, Kimi
  credential identity/HTTP-before-SQL and external effect ordering are preserved.
  Naturally unreachable source branches remain preserved and explicitly bounded
  in the PG handoff rather than made reachable by schema/policy changes.
- Agent Execution Loop v203 records the completed internal boundaries; Model
  Catalog adds new persistence/metadata code paths without changing product
  behavior. No snapshot-wide implementation marker or final plan cleanup.
- Exception ledger: no new cross-I/O lock or material mechanism. The same retained
  reviewer `/root/phase25-independent-review` covered all 53 raw paths / 52 Git
  changes (three import-only equivalence checks and 50 direct reviews), found no
  findings and independently passed 624 cases with no skips. Final frozen patch,
  index and file checks passed. No source correction was required; remaining
  gates are PR creation and exact-head CI. No autonomous merge or issue close.
