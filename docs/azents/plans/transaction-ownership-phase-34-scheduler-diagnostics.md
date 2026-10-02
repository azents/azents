---
title: "Transaction Ownership Phase 34: Scheduler and Ingress Diagnostics"
created: 2026-10-02
tags: [backend, scheduler, external-channel, database, architecture]
---

# Phase Execution Plan

- Phase: `34, complete Scheduler state and bounded ingress control/diagnostic reads`.
- Branch/base: `refactor/transaction-ownership-261002-22-scheduler-diagnostics` ->
  `refactor/transaction-ownership-261002-21-runtime-protocol`, parent PR #2065
  exact head `24bc7d8b1ac0c9b75aa0eaabfa69dadc8abfa958`.
- Start gate: Phase 33 PR exists; root 867 focused / 7,570 full backend cases,
  retained all-24-path independent review with no findings / 867 independent cases,
  type/Ruff/format/pre-commit/OpenAPI and removal gates passed. Parent actual-head
  workflow completed successfully: 33 native checks succeeded, two unchanged-path
  checks skipped; rollup 34 passed / two skipped includes one inherited base status.
  Required E2E four shards, web shard and aggregate passed; OPEN/MERGEABLE/CLEAN.
- PR boundary: nine existing application-owned factory contexts: Scheduler seven,
  guarded Testenv ingress release one and explicitly included observation read one.
  This diagnostic is completed rather than silently excluded. Registered maintenance
  handlers and broader ingress admission/drain/recovery remain named service residuals.
- Inputs: existing ScheduledTaskState and narrow state repository; existing ingress
  queue/owner/diagnostic DTOs and narrow queries; actual JobRuntime and job builders;
  current Periodic Execution and External Channel Provider Ingress Specs.
- Deliverables: seven completed Scheduler operations, two completed ingress reads,
  session-free orchestration/API controls, actual DI/caller/fixture closure, genuine
  PostgreSQL atomicity/independent contention and post-completion external witnesses.
- Non-goals: schema/API/protocol/permission/provider/infrastructure changes, new
  lease/attempt/expiry/version fence, SQL clock conversion, registry enable policy,
  retry/deadline/poll/default changes, job cancellation/claim cleanup, outbox/replay,
  locks/fallback/HA behavior, public Toolkit OAuth or maintenance-handler rewrites.
- Approved mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
  REQ-1 through REQ-5; [ADR](../adr/transaction-260908-repository-ownership.md)
  ADR-D1 through D3; [DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1; unchanged current Periodic Execution, JobRuntime and bounded ingress
  controls/diagnostics contracts. Design delta: `None`.

## Ownership and Required Interfaces

| Workstream | Owner | Owned paths | Depends on | Output / validation |
| --- | --- | --- | --- | --- |
| Scheduler operations and orchestration | `/root/tx-chat-inventory` | scheduler/service.py and service_test.py; new repos/scheduler_state_operations.py and necessary pure data only | Original state queries and preserved application registry/clock behavior | Seven completed operations, required service repository field, old definitions preserved, focused tests/type/Ruff/format |
| Scheduler PostgreSQL proof | `/root/tx-engine-input` | new repos/scheduler_state_operations_test.py and bounded private test helpers only | Published required source contract | Real registration/claim/settlement fault/cancel/closure matrix; independent PID/barrier claim/reclaim/stale-owner evidence |
| Ingress release and observation closure | `/root/tx-platform-inventory` | api/testenv/external_channel_ingress/v1/__init__.py and route_test.py; services/external_channel/ingress_observability.py and defining callers/tests; new completed repos/external_channel/ingress_control_read.py/tests and session-free release service/tests | Original queue/owner/diagnostic queries and actual JobRuntime builder | Two completed reads, Routes -> Services -> Repositories, preserved guarded controls and sanitizer, real PG/external witnesses and all actual caller updates |
| Integration and delivery | `/root` | scheduler/deps.py exclusively; plans and current Specs; global integration/QA/review/PR/CI | All frozen owner handoffs | Explicit production Scheduler DI, integrated checks, frozen full diff, same retained reviewer and exact-head CI |

No owner edits root/peer paths, stages/commits/changes branches/creates PRs or runs
global format/pre-commit while implementations are active. Publish exact contracts
before dependent tests/root DI. Owners remain within the fixed scope; local names or
layout can be refined without inventing behavior or authority.

### Scheduler completed boundary

`SchedulerStateOperationRepository` has required injected session manager and narrow
ScheduledTaskStateRepository. It owns exactly the original groups:

- `ensure_registered_states(*, task_keys: tuple[str, ...], now)` -> None: one
  transaction for all ordered code keys, including disabled definitions; no handler,
  registry function, DI container or arbitrary callback argument.
- `list_states()` -> existing ordered list of detached ScheduledTaskState.
- `get_state(task_key)` -> existing detached state or None.
- `trigger(*, task_key, now)` -> state or None.
- `claim_due(*, task_key, now, lease_owner, lease_until)` -> state or None.
- `mark_success(*, task_key, lease_owner, finished_at, next_run_at, result_summary)`
  -> state or None; required nullable summary retains the existing validated opaque
  TaskResult/query JSON shape, not a new serializer or validation policy.
- `mark_failure(*, task_key, lease_owner, finished_at, next_run_at, error_code,
  error_message)` -> state or None.

SchedulerService requires this completed `repository` plus its existing JobRuntime.
Original generated scheduler_id/poll defaults and public method interfaces remain.
Registry access, clock capture, enable filtering, retry calculation, job construction,
submit/wait, exception handling and logs stay application-owned. Root updates the
single production get_scheduler_service constructor in scheduler/deps.py; all three
existing direct service test constructors use completed operations.

### Ingress completed boundary

`ExternalChannelIngressControlReadRepository` requires the session manager and
existing queue repository, and exposes completed owner and diagnostic reads:

- `get_release_owner(*, owner_id)` -> existing canonical detached owner or a named
  frozen owner-id/created-at projection, or None. Preserve the explicit read commit.
- `inspect_active(*, now, limit)` -> existing sanitized diagnostic snapshot, with
  explicit commit/closure before process metrics.

A session-free release service requires this repository and actual JobRuntime. It
performs owner lookup, returns normal not-found for API 404, otherwise submits the
existing exact job request and returns acceptance without waiting. Unexpected errors
and cancellation propagate. No raw API/JobRuntime/metrics object enters a repository.
Observation service replaces its manager/raw query fields with the completed read
repository; its existing Observation DTO, metrics/runtime dependencies, public limit
and process projection stay unchanged. Actual CLI/API/DI/test callers are updated
at their defining modules. No compatibility exports or optional raw constructors.

## Preserved Scheduler Behavior

- Ensure all registered states together at captured application UTC now, including
  disabled definitions. Preserve separate ensure before list/get/trigger; unknown
  code key returns None only after ensure, without a trigger mutation.
- run_once captures one now for its entire ordered definition loop. Do not resample
  per task or introduce a SQL clock. Due comparison remains <=now; lease eligibility
  remains absent or strictly <now. Existing margin 30s, poll 10s, task intervals,
  timeout/retry rules and UUID defaults are unchanged.
- Success/failure use task_key + lease_owner only. No lease expiry, attempt start,
  status, version or generation guard is added. Existing stale normal None still
  permits application logging. Preserve field clears, failure-streak SQL increment,
  captured-state backoff, result/error shape and current None defaults.
- Claim commits before submit/wait; success/failure settlement is separate afterward.
  Missing attempt_started_at raises before the submission try. Startup ensure failure
  propagates; ordinary per-definition errors continue; cancellation re-raises.
- A cancelled waiter does not clear a committed lease or cancel the shielded accepted
  job. Success-recording failure is outside the submission catch and must not become
  failure-recording. Failure-recording error leaves the prior lease for normal expiry.
- Existing JobRuntime backend, coalescing identity, deadline, manual flag, local
  concurrency/shield/shutdown policy and registered handlers remain unchanged.

## Preserved Ingress Controls and Diagnostics

- Owner read uses existing PK presence, without a new active flag, row lock, lease
  or timestamp guard. Explicit commit/close precedes missing 404 as well as submit.
- Exact owner.created_at lifecycle identity, UTC normalization, payload owner_id,
  handler and application-now +10min deadline are unchanged. Acceptance does not
  await drain; submit/cancel errors do not become accepted success or DB rollback.
- Diagnostic aggregate/ordered bounded read closes before metrics.snapshot, Runtime
  counts and CLI formatting. Existing limits, redaction and private-data exclusions
  stay intact. The operator CLI remains read-only; guarded Testenv release/wake
  controls retain existing LOCAL + enabled app guards and schemas.
- Broader ingress lease/admission/recovery services are not blanket exemptions or
  silently remediated. Public OAuth eight contexts and Runtime-facing service/shared
  Session helper residuals remain separate work; do not expand into them here.

## Removal, Integration and Verification

Remove nine scoped application lifetimes and manager/AsyncSession/SQLAlchemy imports,
Scheduler raw state-query fields and all obsolete test no-op SQL/cast adapters. Keep
narrow queries, executed migrations, live registry/task handlers, valid SchedulerService
CLI callbacks and current job builders. No factory alias, borrowed Session, general
transaction runner, compatibility constructor/export or reverse application import.

Preserve exact old names/order: Scheduler service five definitions, executor two,
state query four and ingress route four (recount actual AST baseline before changes).
Original state-query sequential claim test is not independent contention evidence.

Owners prove actual PG batch ensure atomicity, existing ordered/detached/unknown/disabled
outcomes, due/lease equality, field/streak/summary/error settlement and normal stale
owner outcomes. Independent connections assert distinct PIDs and deterministic barriers
or authoritative blocking state for claim/reclaim/settlement; scoped cleanup is required.
Inject faults/cancellation after real registration/trigger/claim/success/failure writes;
rollback only the active operation while earlier completed ensure/claim remains committed.
Actual task cancellation and JobRuntime submit/wait/log/metrics spies verify no active
SQL context on success, error, cancellation and no-op. API owner/missing/submission
failure/cancel and sanitizer/observation/CLI cases use real SQL or typed completed
operation doubles, never fake ownership lifetimes.

Integration order: publish source contracts -> PG/ingress tests and root DI -> owner
focused frozen handoffs -> root integrated focused/full backend, whole ty, changed-path
Ruff/format, pre-commit, docs/whitespace, public/admin and bounded Testenv OpenAPI equality,
all caller/helper/alias/import/removal/source scans -> freeze -> same retained read-only
`/root/phase25-independent-review` complete-diff review -> grounded fixes/affected checks
-> commit/stacked PR over #2065 -> exact-head required CI. Root owns every global check
and review request. No next implementation phase before this phase PR exists.

## Context and Scope Checkpoint

- All three target source fingerprints equal read-only discovery and parent 24bc7d8b1;
  source bootstrap gate recorded outside repository before this tracked plan.
- Comparable baseline 495 contexts / 89 files. Expected bounded delta nine ->486
  across API eight, Scheduler zero, services 477 and fixture one. Verify actual
  counts; they are not full alias/indirect coverage or verified remaining violations.
- Runtime 66-file supplementary source audit found no additional internal application
  SQL lifetime but named existing Auth/Registration/Profile/Provider/Recreation and
  Session-sharing service contracts. Those overlap service inventory, not new count.
- Implementation and all three owner handoffs are frozen: Scheduler application
  21 cases, Scheduler PG 52 cases and extended ingress 46 cases passed separately;
  overlapping counts are not added. All 12 owner hashes match their acceptance
  manifests; root's dependency wiring is the thirteenth changed Python path.
- Root integrated QA passed 183 focused and 7,664 full backend cases, with only
  three existing Redis-specific memory-backend contract skips in the full suite.
  Whole ty, Ruff/format for 13 Python files, public/admin 234/69 and bounded
  three-path ingress OpenAPI equality, docs/whitespace and removal/caller/import
  scans passed. No source bytes changed during integrated QA.
- Actual inventory is 486/86 after the bounded nine-context reduction. All
  original service/executor/state-query/route names and order remain; the narrow
  state query and its four tests are byte-identical. Eighteen distinct-connection
  cases carry backend-PID and authoritative blocking-state evidence. Other
  genuine savepoint-backed and actual LocalJobRuntime proofs remain separate.
- Root verification-only corrections recognized explicit positional injection
  and class-scoped test definitions; product source was not altered for a scan.
  Immutable parent enumeration was reused while current source was re-inspected.
- Periodic Execution 24 and Provider Ingress 64 record internal completed groups
  and preserved timing, settlement, accepted-job and read/metrics/submit ordering.
  Initial/final pre-commit passed with source bytes unchanged. The same retained
  reviewer covered all 18 paths with no findings, independently passed 183 cases
  without skips, repeated the overlapping 18 contention cases and verified bounded
  OpenAPI plus final frozen checks. Only execution metadata changed afterward.
  Commit/PR and exact-head CI are pending.
  Design delta None; no new cross-I/O lock, live infrastructure/provider/credential
  change, Agent merge, implemented marker or issue #1718 closure.
