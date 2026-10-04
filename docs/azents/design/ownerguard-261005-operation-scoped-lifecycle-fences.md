---
title: "Operation-Scoped Execution and Lifecycle Design"
created: 2026-10-05
tags: [backend, concurrency, execution, lifecycle]
document_role: primary
document_type: design
snapshot_id: ownerguard-261005
---

# Operation-Scoped Execution and Lifecycle Design

## Design Authority

Revision: 2. [Requirements](../requirements/ownerguard-261005-operation-scoped-lifecycle-fences.md) and [ADR](../adr/ownerguard-261005-operation-scoped-lifecycle-fences.md) share snapshot `ownerguard-261005`.

- M1 (derived): exact Session owner mutation fence and independent descriptive operations without lazy persisted GET repair, `REQ-1`, `REQ-3`, `ADR-D1`, `ADR-D5`.
- M2 (derived): conditional winning claims, hierarchy mutation ordering and atomic terminal/mailbox groups, `REQ-2`, `REQ-4`, `ADR-D2`.
- M3 (derived): precise resource/producer/Channel Work finalization and removal of descriptive lifecycle gates, `REQ-5`, `ADR-D3`.
- M4 (required): complete operation/caller exception audit and deterministic delivered verification, `REQ-6`.

## Design Approval

Direct implementation of the explicitly requested final technical phase. Requester owns fixed read/removal and unchanged execution/security outcomes. Date: 2026-10-05. Revision 2, authority M1–M4 records their derived implementation boundary, including detached GET fallback rather than read-repair writes; no new public response, schema, token, mode or recovery authority is introduced. Unresolved material departures return to Requirements/ADR while independent implementation continues. CI is checked in parallel, not a prerequisite to starting remaining work.

## M1 — Execution Operation Boundary

Replace `OwnerBoundSessionManager` and direct WorkerSession root-gate inheritance with explicit operation authority. Plain reads and harmless metadata use normal read/write capability without root/Agent/ancestor ownership exclusion. Retain the existing `SessionExecutionOwner` identity in operation dependencies so critical mutations do not lose captured generation.

A critical output/promotion/terminal transaction locks or conditionally mutates only the exact owner Session row, verifies its generation and retains the fence until dependent writes commit. Owner acquisition/handover participates in the same exact row ordering. Do not implement an unrelated INSERT guarded only by MVCC `EXISTS`; it does not make owner handover wait. A plain pre-I/O owner check may reject current stale admission but is not a lock across network execution. Actual tool/Runner/resource admission and final completion guards remain separate.

Model preparation's generic root-owner assertion is replaced with nonlocking current-owner validation or removed when redundant; it does not grant side-effect authority. No ordinary event/result/private-state load inherits the new mutation fence. Rewrite implicit with-owner/for-execution factories into explicit critical operation binding and independent descriptions; do not retain a generic compatibility wrapper.

Chat GET fallback is a detached description using existing response selection
rules. It neither repairs stored applied fields nor increments persisted profile
generation; tests assert both unchanged public fallback and unchanged stored
bytes/generation. Actual profile/operation admission continues its existing
capture/revalidation/reconciliation mutation. The conditional no-op owner fence
explicitly preserves `updated_at`, avoiding ORM on-update timestamp changes.

Existing PostgreSQL foreign-key/unique constraints remain unchanged. Native
deferred FK checks may still wait on parent writers during real critical commit;
the removed explicit generic gates do not imply lock-free mutation commits.

## M2 — Claims, Mailbox and Hierarchy

Session owner/pending Run/scheduled/ingress/job claims use existing status, generation, lease and work identities at the atomic mutation. Preserve cycle/Run/mailbox/event/start grouping. Exact child terminal delivery disposition and idempotent parent mailbox admission commit together; no separate unguarded parent read can authorize duplicate delivery.

Multi-Session tool mutations acquire the exact participating Session set in
stable order, using whole-savepoint NOWAIT retry where necessary to release all
partially acquired rows. Owner mutation occurs only after that set is held.
This prevents a parent tool retaining one row while waiting on a child whose
terminal publication needs the parent. Standalone repair delivery owns the
completed Run disposition and exact active mailbox target, not a root-tree gate.

Actual public Stop callers authorize by plain read before whole-tree mutation
admission and reauthorize after acquisition. They do not retain a partial
Session/Agent lock outside the retry savepoint; otherwise a child terminal
writer waiting for its parent could prevent the retry from ever progressing.

Stop/cancellation/archive/purge/decommission and new-child creation participate in their actual hierarchy mutation ordering. If an ancestor/root fence is still required to prevent a child escaping a critical transition, scope it to those mutations and register exact rows/outcome. Ordinary descendants/status reads do not take it. Keep irreversible purge fence, no-active-Run settlement, restore cutoff, participant progress and tombstones. No new token or persistent state authority is created.

## M3 — Resource, Producer and Channel Work

Runtime removal/recreation/report/ack finalization uses exact Runtime/desired/Runner/connection/configuration and dispatched attempt/lease identities. Reject replacement acknowledgements and obsolete producer completion. Existing worktree path overlap claims remain actual resource admission, not global lookup serialization. Cleanup inventory tolerates stale/missing references while actual irreversible action validates exact target.

Channel Work uses existing Toolkit State CAS, work cycle and progress revision to reject obsolete provider outcomes. Harmless private snapshot/dedupe/state mutations do not inherit whole-tree ownership serialization. Actual critical event/output/security publication remains fenced separately.

Preserve already verified current-input capability acceptance, credential finalization and Memory producer publication. A shared helper is split by actual operation when used by both descriptions and final mutation; it is not globally unlocked merely to shrink an inventory count.

## Removal and Replacement

- Generic OwnerBound root/Agent/parent gate and direct read-facing execution-lock helpers: explicit independent descriptions and exact owned mutation operation.
- Blanket with-owner transaction factories: existing owner identity injected into critical operations only; no raw session forwarding shim.
- Read/status/cleanup freshness locks and stale-tree-count errors: scoped retained observations/normal missing result; real hierarchy/resource mutations retain exact ordering.
- Root-lock order tests without a public guarantee: nonblocking read and competing claim/stale-result/Stop/resource outcome tests.
- Remaining row/advisory/raw SQL/wrapper sites: operation-specific E1/E2/E3 register with caller, exact fields, shortest scope, simpler conditional-write alternative and deterministic test.
- No schema, API/client/configuration/cache/compatibility or discovery/static-prompt policy changes.

## Test Strategy

Existing required execution, scheduled/external, Runtime/worktree, cancellation/archive/purge and parent/subagent suites form the E2E primary matrix. Preserve provider prerequisites and optional/live credential skip policy. Complete backend quality and delivered-SHA CI run for each reviewable delivery, with implementation continuing during external waits.

Real PostgreSQL tests use events/held authoritative rows to prove successful descriptions while old root/Agent/parent writer locks are held, exact Session mutation fence against handover, one pending/leased claim, stale output rollback, exact mailbox promotion, single parent delivery, child creation versus Stop/purge, post-fence restore rejection, and replaced Runtime generation/ack rejection. Test an owner change between preparation and commit; no stale events/result may persist. Preserve one-time auth and privacy/captured-input tests. No sleeps establish correctness ordering.

## Feasibility and Operations

Existing owner generations, statuses, unique/idempotent work identities, lease/attempt state and resource generations provide the required authority. Multi-row mutation requires a real exact-row commit fence, not an application-only precheck. Final residual audit runs after all current phase changes; counts are source sites, not unnecessary percentages. Any unclassified/non-exempt site remains unfinished work. No Agent merge, deployment or live mutation is authorized.
