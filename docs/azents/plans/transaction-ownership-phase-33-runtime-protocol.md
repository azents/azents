---
title: "Transaction Ownership Phase 33: Runtime Protocol"
created: 2026-10-02
tags: [backend, runtime, architecture, database]
---

# Phase Execution Plan

- Phase: `33, complete Runtime protocol ownership/report/reconciliation boundaries`.
- Branch/base: `refactor/transaction-ownership-261002-21-runtime-protocol` ->
  `refactor/transaction-ownership-261002-20-worker-executor`, parent PR #2060
  head `b71c391fb473463d48fee9608f8a6beeea0cb3c0`. Reconcile requester-merged
  main if needed; never merge autonomously.
- Start gate: Phase 32 PR exists; root 624 focused / 7,419 full cases and retained
  independent 53-path review / 624 cases passed. Parent exact-head CI is confirmed:
  34 passed, two unchanged-path skips, no failed/pending checks, MERGEABLE/CLEAN.
  Phase 33 implementation may start.
- PR boundary: 16 existing application-owned factory contexts in four files:
  owner registry/manager five, data-plane route read one, Provider/Runner report
  sinks five and RuntimeLifecycleReconciler five. Other Runtime paths are not
  blanket exclusions or silently remediated. Factory count is not operation count.
- Inputs: existing RuntimeWebSessionRoute query primitives, AgentRuntime and
  RuntimeProfile repositories, completed RuntimeLifecycleDispatchRepository,
  current epoch/configuration/offer/lease/nonce and coordination contracts.
- Deliverables: completed domain route/report/reconcile operations, session-free
  application adapters, canonical detached results and evidence helpers, all
  actual constructor/caller/fixture updates and genuine PostgreSQL boundary proof.
- Non-goals: protocol/protobuf/schema/API/permission changes, provider or live
  infrastructure work, new stream replay/resume/delivery/fallback/HA behavior,
  lock order normalization, distributed locks, TTL/grace/retry/deadline policy,
  broad data-plane/coordination rewrite or compatibility constructors/callbacks.
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; current Agent Runtime Control/Persistence, Run Resume and optional
  Redis contracts. Design delta: `None`.

## Ownership and Required Interfaces

| Workstream | Owner | Owned paths | Required output | Validation |
| --- | --- | --- | --- | --- |
| Owner/route and data-plane closure | `/root/tx-engine-input` | runtime/stream_session_owner.py/tests; runtime/control_protocol/grpc/runtime_stream_session_server.py/tests narrow route/constructor changes; new completed route repository/data/tests | Six assigned contexts; completed acquire/renew/resolve/consume/drain/release and required detached route/epoch contracts, no Session-taking JoinRepository protocol | Nonce single winner, epochs/SQL-clock lease/deadline, postcommit expiry/cancel/registration, gRPC/capacity/broker/registry effects after closure |
| Provider/Runner report persistence | `/root/tx-platform-inventory` | runtime/control_protocol/grpc/state_sinks.py/tests; new report operation repository/data/tests; necessary canonical evidence/report pure definitions and actual defining callers | Five contexts and three Session-taking evidence helpers become exact DB-only compositions; publish constructors before root wiring | Atomic evidence/observation/connection/failure rollback, stale normal-return commits, distinct restart handoff, registration/ack/path/error semantics |
| Reconciliation persistence | `/root/tx-chat-inventory` | runtime/control_protocol/reconciler.py/tests; new reconciliation operation repository/data/tests | Five completed candidate/timeout/profile/marker/config/repair groups, unused Agent query dependency removal only if no caller consumes it | Ordered/suppressed candidate lists, committed marker despite dispatch false, post-coordination authority, timeout order, error/cancel/no-op closure |
| Integration and delivery | `/root` | runtime/control_server.py explicit constructors/wrappers only; phase/master plans and related Specs; global integration fixes/QA/review/PR/CI | Shared composition root exclusively root-owned to avoid coedit; owners send required exact constructor/DTO methods first | Whole backend/type/Ruff/format/pre-commit/OpenAPI, all caller/removal/source coverage, frozen diff, same retained reviewer and exact-head CI |

- Each owner reads current scopes and bounded static discovery; source map is
  supporting evidence, not authority to alter product/protocol behavior.
- New repositories compose existing narrow queries inside completed operations.
  Return existing detached DTOs or named frozen data, never live SQLAlchemy/Session
  objects, factories or arbitrary application callbacks. Do not move the 121KB
  data-plane implementation into a repository.
- Publish required operation/constructor contracts and shared canonical pure
  types before peers/root integrate. Repositories do not reverse-import Runtime,
  service, API, broker/provider/gRPC machinery. Keep validated protobuf decoding,
  local authentication/profile/offer/clock/locks and all external effects outside.
- Root exclusively updates all six production constructors in control_server's
  lifespan (sinks, owner manager/registry, data plane, reconciler) and RuntimeWeb
  wrapper injection. Other actual defining callers move only when required.
- Owners never edit root or peer files, stage/commit/change branches/create PRs
  or run global formatting/pre-commit while others implement. Focused tests and
  logs stay scoped; all stable owner handoffs precede root final validation.

## Owner/Route Semantics

- Existing SQL(now) is lease/deadline authority. Keep Runtime/route FOR UPDATE
  validation, exact epoch/generation/fingerprint/boot/nonce hash, current TTL and
  conflict/expired replacement rules. Acquire locks Runtime then route; renew,
  resolve and consume_join lock route then Runtime. This existing asymmetry is
  preserved, not normalized or hidden with a new retry.
- Resolve stale/expired/draining returns None and catches only current RouteConflict.
  Consume exact current offer and nonce once; mark-draining exact current epoch
  and TTL once; release exact epoch returns bool without a new expiry/drain guard.
  Renew extends route lease but not the original offer deadline.
- Registry hello/auth/profile/local offer checks remain before database consume.
  Local deadline is checked again after committed nonce consumption: expiration
  raises while the nonce remains consumed. Do not roll that consumption back or
  add replay/compensation. Accepted registry insertion occurs under its existing
  local lock afterward; duplicate join keeps its current failure.
- Owner acquire/renew/drain/release resolve database work before local ownership
  map, offer projection and callbacks. Preserve cancellation and exact-epoch local
  cleanup; never delete replacement ownership. Current gRPC status translation,
  one-hop relay, drain/open linearization, queue/dequeue credit and capacity remain.

## Provider/Runner Atomic Groups

- Provider report with missing Runtime returns without killing its stream; immutable
  binding mismatch remains ValueError. Terminal-delete acknowledgement and existing
  state/path/connection writes remain one report transaction. Ordinary report
  evidence/promotion, observed state/failure and CONNECTED remain atomic.
- Preserve stale CAS returning None/normal exit, including earlier configuration
  changes that currently commit. Do not convert it to rollback or a new error.
- Restart binding and conditional rearm remain their own later operation, not merged
  into report persistence. Command correlation and Provider generation gates stay
  in application decoding before persistence; no provider client call in a repo.
- Runner missing Runtime remains ValueError. stopped+runner_stream_closed writes
  DISCONNECTED and returns before path/evidence handling. Desired-generation mismatch
  stays a no-op. BUSY maps READY; missing/relative workspace records existing failure,
  not a new raise or filesystem lookup. Path normalization stays pure.
- Runner evidence/promotion, state/path/failure and eligible failure clearing share
  the existing transaction. Registration accepts current OR retained-applied config;
  heartbeat yields only the Provider-first ready pending exact desired evidence.
  RuntimeWeb generation_gate.mark follows completed delegate, never inside SQL.

## Reconciliation and External Machinery

- Load three candidate lists in one completed snapshot, preserve order/limit and
  suppression: lifecycle IDs exclude adoption/observe, adoption excludes observe.
  Candidate snapshots are hints, not final authority.
- Periodic profile predicate and observe-requested marker commit together even if
  later dispatch returns false. Adoption snapshot remains a separate read; pure
  impact mapping follows completion. Observe repair keeps exact runtime/provider/
  generation/ready/applied predicates; final dispatch uses existing completed
  preflight/claim revalidation after coordination lookup.
- Timeout mutation remains separate AFTER refresh/dispatch. Preserve current normal
  outcomes, unknown result handling, transparent cancellation and per-record behavior.
  No new durable repair record, outbox, replay, claim or provider retry.
- Existing dispatch path stays completed preflight -> external coordination ->
  completed claim -> pure credential identity -> external protocol dispatch ->
  completed outcome. Do not redesign already completed dispatch transactions.
- Capacity memory/Redis degraded behavior and epoch restoration are existing volatile
  projections; PostgreSQL epoch/generation/lease remains authority. Preserve optional
  Redis semantics without making it durable ownership or new multi-process outage
  fallback. Existing local locks may span DB operations; add no cross-I/O lock.
- Keep current provider/observe deadlines10s, lifecycle retry15s/start timeout5min,
  heartbeat5s/two misses10s and finite/long-lived grace120s/5s. This extraction does
  not adjust timeouts or resolve pre-existing protocol/lock issues.

## Removal and Validation

- Remove 16 assigned application lifetimes/SQLAlchemy/AsyncSession/SessionManager
  fields and reconciler alias _session_manager, three report Session helpers and
  old live-Session join Protocol. Remove unused reconciler Agent collaborator only
  after actual caller proof; live query/dispatch primitives remain.
- No generic DB runner/Session alias/optional raw constructor/compatibility export.
  Replace owner/server/reconciler/sink fixture adapters that simulate application
  SQL with completed operations or genuine PostgreSQL wiring; preserve all existing
  static owner9/reconciler18/sink20/server29/route5 test definitions.
- Real independent PostgreSQL sessions/barriers prove nonce one winner, acquired
  conflict/replacement, stale epoch/generation, SQL-clock TTL and scoped cleanup.
  Savepoint-backed fixture tests alone do not establish connection contention.
- Inject actual write faults/cancellation between report evidence/promotion/state/
  connection/failure clear and restart rearm to prove original atomicity. Test
  Provider missing-ignore vs Runner missing-error, terminal-delete, retained applied,
  future/lower generations, postcommit nonce expiry and exact owner release.
- External spies assert no active SQL context/transaction before coordination,
  provider dispatch, capacity Redis, broker/gRPC queues/abort/relay/cleanup, local
  registry projection and generation gate callbacks on success/error/cancel/no-op.
- Root integrated focused/full backend, whole ty --error-on-warning, changed-path
  Ruff/format, pre-commit, exact OpenAPI/schema/client equality and explicit
  constructor/caller/import/alias/helper/removal scans. Baseline strict inventory
  511/93; expected bounded delta16 is verified, not treated as a completion estimate.
- Same single retained reviewer `/root/phase25-independent-review` reads the complete
  stable root-integrated diff only after all handoffs/root QA. Root owns corrections
  and material targeted re-review. Open stacked PR before another implementation
  phase; required exact-head CI/E2E must pass. Never merge/close autonomously.

## Context and Scope Checkpoint

- Current four source fingerprints exactly equal read-only discovery/e14 bytes
  after Phase32 commit b71c391fb; baseline counts5/1/5/5=16. No confirmed active
  external overlap in inspected closures, not a global exclusion/coverage claim.
- Parent Phase32 root624/7419pass3existingRediscontract skips; wholety/Ruff48/
  format/pre-commit/OpenAPI23469/removal0. Retained review53raw52GitNoFindings and
  independent624pass. PR #2060 head b71c391fb is OPEN/MERGEABLE/CLEAN with
  34 passed checks and two unchanged-path Helm/TypeScript skips, none failed/pending.
- No live cluster, Provider, credentials, resources, DB schema or infrastructure
  change authorized. All tests use isolated fixtures/fakes; do not expose tokens.
- Approved M1-M5 behavior/removal covered; Design delta None only while exact
  current protocol/epoch/TTL/error/lock/cancel/fallback/atomicity is preserved.
  Material unsupported mechanism requires separate authority, not implicit approval.
- Implementation and owner-focused evidence are frozen: route 95, report 166,
  reconciliation 51 cases passed separately; overlapping cases are not summed.
  All 18 owner file hashes match their final acceptance manifests. Root supplies
  the six required production constructors; 19 changed Python files in total.
- All original owner 9/server 29/sink 20/reconciler 18 test definitions and their
  order remain. The existing narrow route query and its five tests are unchanged.
  Eight genuine distinct-connection PostgreSQL races use barriers or authoritative
  blocking-state witnesses. Other write-fault/cancellation and coordination-drift
  tests use genuine savepoint fixtures without claiming independent contention.
- Root integrated QA passed: 867 focused and 7,570 full backend cases, with only
  three existing Redis-specific memory-backend contract skips. Whole backend ty,
  Ruff/format for 19 Python paths, exact public/admin OpenAPI 234/69 equality,
  docs/whitespace and boundary/removal/caller/helper/import scans passed.
  No source bytes changed during integrated QA. Comparable candidates decrease
  from 511/93 to 495/89; Runtime has zero direct lexical candidates, not complete
  alias/indirect-call coverage or overall issue completion.
- Current Specs record only internal completed boundaries: Runtime Control 92,
  Runtime Persistence 41 and Run Resume 38. Successful adoption alone suppresses
  observation; normal stale commits, post-consume expiry, original lock ordering,
  separate restart rearm and timeout sequencing remain unchanged.
- No new cross-I/O lock was necessary; exception ledger None. No schema, API,
  protocol, provider, TTL, retry, fallback, replay or live infrastructure change.
  Initial and final pre-commit passed with no source changes. The same retained
  reviewer covered all 24 paths with no findings and independently passed 867
  cases with the same three existing skips. All frozen source/index/diff checks
  passed. This post-review checkpoint changes execution metadata only.
  Commit/stacked PR and exact-head CI remain pending. Issue #1718 stays open;
  no Agent merge or implemented markers.
