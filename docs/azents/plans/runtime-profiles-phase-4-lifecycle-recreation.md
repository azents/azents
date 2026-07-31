---
title: "Runtime Profiles Phase 4 Lifecycle and Recreation Plan"
created: 2026-07-31
updated: 2026-07-31
tags: [runtime, lifecycle, recreation, backend, api]
---

# Phase Execution Plan

- Phase: `4 — Runtime lifecycle and scoped recreation`
- Branch/base: `feature/runtime-profiles-06-lifecycle-recreation` → `feature/runtime-profiles-05-provider-protocol`
- PR boundary: latest-ready lifecycle guards, in-place versus recreate adoption, durable scoped
  recreation worker, Admin/Public operation APIs, and removal of the remaining legacy Runtime
  execution-policy authority
- Inputs: Phase 2 immutable desired/applied revisions and recreation tables; Phase 3 exact configuration protocol/evidence and Provider lowering
- Deliverables: atomic lifecycle command guards; blocked-safe stop/terminal delete; Kubernetes
  network-only in-place adoption through generation-fenced Runtime Control and Runner state evidence;
  recreation operations for Provider, infrastructure Profile, and Workspace Runtime Profile scopes;
  bounded concurrency/retry/progress/failure projections; migration of lifecycle/tool/decommission/
  worker/status callers; projected applied migration state; deletion of legacy services,
  repositories, permissions, snapshots, and Agent overrides through a forward Alembic migration;
  regenerated protobuf and OpenAPI clients
- Non-goals: product UI, testenv E2E journeys, migration validation report, living-spec promotion, rollout deadlines/stages, cancellation API, or live infrastructure changes
- Interfaces: create/start/restart/reset/recreate require the exact current desired revision to be
  `READY`; stop and terminal delete do not require a ready revision; only Kubernetes
  `network_policy`-only changes are in-place in v1; all PodSpec/PVC/Docker changes wait for
  recreation; an exact current-generation Provider `RUNNING` report and matching Runner ordinary
  state report are required before applied promotion; operation Runtime/revision targets are
  snapshotted once under the requested source version; the exact source version is reread under a
  shared mutation-blocking lock before dispatch; changed pre-dispatch targets and superseded exact
  dispatches are skipped rather than refreshed or redispatched; PostgreSQL transaction-held item
  locks and generation fencing are authoritative and Redis is not required; no runtime caller,
  dependency wiring, permission, status projection, or persistence fallback retains legacy
  execution-policy authority
- Removal obligations: Runtime Execution Policy domain/services/repositories/direct tests and
  dependency wiring; execution-policy permission resource; Agent Provider overrides and Runtime
  policy snapshots; legacy applied-status fallback; legacy capability `execution_policy` branch and
  parser/adapter; repeated compatibility preparation; duplicate Profile parsing and Provider-local
  lifecycle models/adapters; dedicated Runner configuration-update request/ACK/relay and separate
  completion state; two-step lifecycle generation/configuration-revision repair; overlapping
  reconciliation action loops; all exact residuals handed forward from Phase 1–3 under the one-time
  final-stack-equivalence exception
- Absence verification: production import and dependency-wiring searches return no legacy policy
  caller; permission/schema searches and generated migration roundtrip prove obsolete state removal;
  one canonical Profile parser and compatibility preparation path remain; Docker/Kubernetes consume
  shared lifecycle types directly; no dedicated configuration-update operation remains; lifecycle
  state and exact target evidence advance atomically; one reconciliation action classifier remains;
  backend, shared-control, and Provider integration suites pass

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Lifecycle guard and impact classification | `/root` | `python/apps/azents/src/azents/services/agent_runtime/**`, `python/apps/azents/src/azents/repos/agent_runtime/**`, Runtime Profile core/repository, reconciler | exact desired revisions | atomic ready-revision guard; waiting/in-place/recreate classification | lifecycle race, blocked command, generation, and stale-revision tests |
| Runner evidence adoption | `/root` | Runtime Runner protobuf, shared control library, backend Runner gRPC bridge, Runner process/tests | exact Provider evidence | generation-fenced evidence adoption using the existing control/state-report authority path; dedicated update operation deleted | protobuf absence search, round-trip, stale update, and state-report tests |
| Kubernetes in-place adoption | `/root` | `python/apps/azents-runtime-provider-kubernetes/**` | impact classification and exact evidence | NetworkPolicy/evidence adoption without Pod/PVC replacement | rendered resource and evidence tests |
| Recreation persistence and worker | `/root` | Runtime Profile repository/data, new recreation service, Runtime Control loop | recreation schema foundation | stable Runtime/revision snapshots, pending claims and transaction-held RUNNING locks, shared source-version dispatch fence, exact dispatch evidence, changed/superseded skips, bounded retry, completion counters | peer-worker exclusion, target-version race, partial failure, retry terminality, supersede, and shutdown-boundary tests |
| Admin/Public APIs | `/root` | Admin Provider API, Public Runtime Profile API, service authorization | recreation service | authority-scoped create/get/progress/failure endpoints | authorization, ownership, target-version, and response tests |
| Legacy authority removal | `/root` | execution-policy domain/repositories/services/tests, runtime-provider policy persistence, Agent Runtime legacy columns, permissions, engine/tools, decommission, worker wiring, generated Alembic revision | replacement lifecycle and exact applied projection | no active legacy authority; Provider-global capability/config history retained | import/wiring search, migration roundtrip, status equivalence, backend quality checks |
| Generated clients and integration | `/root` | OpenAPI specs and generated Python/TypeScript clients | API contracts | synchronized clients without UI consumption | supported generation scripts and generated-artifact checks |

- Integration order: phase plan → lifecycle atomic guard and one impact/action classifier → Runner
  evidence adoption → Kubernetes in-place handling → recreation repository/service/worker →
  authority-scoped APIs → migrate remaining internal callers and applied projection → delete legacy
  authority and generate the forward migration → protobuf and OpenAPI/client generation → focused
  and full validation
- Independent review: `hardtack`, focusing on authorization scope, generation/revision fencing, PVC
  and data preservation, retry idempotency, exact evidence, absence of automatic recreation outside
  explicit operations, and proof that Provider-global operational configuration is preserved while
  legacy Runtime policy authority is removed
- Final validation: backend Ruff/format/Pyright/Pytest; Kubernetes and Docker Provider quality
  suites; OpenAPI/client generation; generated-client TypeScript/Python checks; migration
  upgrade/downgrade; repository search for legacy imports/wiring/permissions/schema references; full
  stack handwritten source/test diff; commit hooks
- Scope-drift check: no frontend components, E2E fixtures, spec promotion, rollout policy, compatibility fallback, or live deployment changes
- Context checkpoint: Phase 3 protocol is PR #1045. Phase 4 now has atomic ready-revision lifecycle
  transitions; Provider-ACK-to-heartbeat-to-ordinary-Runner-report applied promotion; durable
  Provider, infrastructure Profile, and Workspace Profile recreation operations; exact item locks,
  dispatch evidence, bounded retries, and progress APIs; official OpenAPI/client regeneration; and
  forward removal of active legacy Runtime policy authority. Backend full validation, shared
  Runtime Control validation, and both Provider suites pass. Remaining Phase 4 work is final
  migration/diff review, documentation consistency, commit/PR creation, and CI/review handling;
  Phase 4 creates PR 6/10 before waiting on stack CI
