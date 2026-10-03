---
title: "Periodic Execution Flow Spec"
created: 2026-06-20
tags: [backend, engine, infra]
spec_type: flow
code_paths:
  - python/apps/azents/src/azents/core/agent_errors.py
  - python/apps/azents/src/azents/core/chat_data.py
  - python/apps/azents/src/azents/core/chat_projection.py
  - python/apps/azents/src/azents/core/historical_memory_settings.py
  - python/apps/azents/src/azents/core/historical_memory_snapshot_policy.py
  - python/apps/azents/src/azents/core/session_resource_authority.py
  - python/apps/azents/src/azents/core/session_workspace_paths.py
  - python/apps/azents/src/azents/repos/chat_operations.py
  - python/apps/azents/src/azents/repos/engine_resolve.py
  - python/apps/azents/src/azents/repos/llm_catalog_operations.py
  - python/apps/azents/src/azents/repos/model_metadata_operations.py
  - python/apps/azents/src/azents/scheduler/types.py
  - python/apps/azents/src/azents/scheduler/registry.py
  - python/apps/azents/src/azents/scheduler/executor.py
  - python/apps/azents/src/azents/scheduler/service.py
  - python/apps/azents/src/azents/scheduler/deps.py
  - python/apps/azents/src/azents/repos/scheduler_state_operations.py
  - python/apps/azents/src/azents/scheduler/user_scheduled_task_dispatch.py
  - python/apps/azents/src/azents/job_runtime/deps.py
  - python/apps/azents/src/azents/job_runtime/local.py
  - python/apps/azents/src/azents/job_runtime/registry.py
  - python/apps/azents/src/azents/job_runtime/types.py
  - python/apps/azents/src/azents/services/historical_memory/**
  - python/apps/azents/src/azents/repos/historical_memory/**
  - python/apps/azents/src/azents/repos/historical_memory_consolidation/**
  - python/apps/azents/src/azents/rdb/models/historical_memory_consolidation.py
  - python/apps/azents/src/azents/rdb/models/historical_memory.py
  - python/apps/azents/src/azents/services/file_lifecycle_cleanup.py
  - python/apps/azents/src/azents/services/external_account_link.py
  - python/apps/azents/src/azents/services/external_account_oauth/service.py
  - python/apps/azents/src/azents/repos/external_account_link/**
  - python/apps/azents/src/azents/repos/external_account_oauth/**
  - python/apps/azents/src/azents/utils/logging.py
  - python/apps/azents/src/azents/repos/agent_avatar_cleanup/**
  - python/apps/azents/src/azents/rdb/models/agent_avatar_cleanup.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/097a97177350_create_operational_schema_baseline.py
  - python/apps/azents/src/azents/services/archived_session_retention.py
  - python/apps/azents/src/azents/services/archived_session_purge.py
  - python/apps/azents/src/azents/services/chat/__init__.py
  - python/apps/azents/src/azents/services/agent_decommission.py
  - python/apps/azents/src/azents/services/agent_runtime_removal/**
  - python/apps/azents/src/azents/services/owner_lifecycle.py
  - python/apps/azents/src/azents/services/llm_catalog/**
  - python/apps/azents/src/azents/services/model_metadata_projection.py
  - python/apps/azents/src/azents/repos/archived_session_retention/**
  - python/apps/azents/src/azents/repos/scheduled_task_state/__init__.py
  - python/apps/azents/src/azents/repos/scheduled_task_state/data.py
  - python/apps/azents/src/azents/rdb/models/scheduled_task_state.py
  - python/apps/azents/src/azents/rdb/models/scheduled_task.py
  - python/apps/azents/src/azents/repos/scheduled_task/**
  - python/apps/azents/src/azents/repos/scheduled_task_cycle/**
  - python/apps/azents/src/azents/services/scheduled_task/service.py
  - python/apps/azents/src/azents/rdb/models/archived_session_retention.py
  - python/apps/azents/src/cli/scheduler.py
  - python/apps/azents/src/cli/devserver.py
  - python/apps/azents/bin/scheduler.sh
  - infra/charts/azents/templates/server/scheduler-deployment.yaml.tpl
  - infra/charts/azents/templates/server/scheduler-pdb.yaml.tpl
last_verified_at: 2026-10-04
spec_version: 26
---

# Periodic Execution Flow Spec

Azents periodic execution uses one dedicated Scheduler role for code-registered
maintenance jobs and for bounded admission of user/agent-facing Scheduled Tasks.
The two domains share process packaging and polling but keep separate durable
authorities and execution paths.

## Runtime roles

Production runs periodic execution through a dedicated scheduler role. The production entrypoint is `bin/scheduler.sh`, which applies the RDB revision from `db-schemas/rdb/revision` when needed and then starts `src/cli/scheduler.py run`.

The Helm chart defines a separate scheduler Deployment and PodDisruptionBudget. The scheduler uses
the server image and server environment sources, but it is not the AgentWorker.

Devserver runs Runtime Control, Public API, Admin API, AgentWorker, and Scheduler in
one local process. Runtime Control starts before Worker dependency composition so the
Worker's required trusted transfer coordinator is available. This is local packaging
only; it does not collapse the production scheduler role into AgentWorker.

## Task definition registry

Scheduled task definitions are code-owned. `get_task_definitions()` returns registered `ScheduledTaskDefinition` values.

A definition includes:

- task key
- description
- interval
- timeout
- retry policy
- async handler
- default enabled flag

For the code-owned maintenance registry, the database does not store task
definitions or schedule overrides. It stores current runtime state only. User
Scheduled Task definitions and cron cursors are a separate product domain stored
in `scheduled_tasks`; the maintenance registry stores only the dispatcher
definition that scans that domain.

Registered tasks include `scheduler_heartbeat`, `model_catalog_system_projection`,
`archived_session_retention_recalculation`, `archived_session_purge`,
`session_auto_archive`, `agent_decommission`, `agent_runtime_removal`, `owner_lifecycle`,
`file_lifecycle_cleanup`, `external_account_oauth_cleanup`,
`historical_memory_discovery`, plus the user Scheduled
Task dispatcher definition.
`scheduler_heartbeat` is a no-op heartbeat that returns a small execution
summary and has no external network dependency.

The existing six-hour `model_catalog_system_projection` task collects bounded inert
source JSON, prepares exact per-model normalized prices and system projections, and
atomically replaces the current source and all affected system catalogs. It returns
current publication counts and descriptive source facts, not snapshot IDs, hashes,
fingerprints, or candidate/cutover identities. A failed collection/publication retains
the previous current rows and last-success time with one current failure state.
This task does not backfill saved selections, discover integration models, or change
existing integration synchronization timing/backoff.

The user Scheduled Task dispatcher definition remains code-owned, but its handler
does not use `scheduled_task_states` as product state. Each execution asks the
Scheduled Task domain service to claim a bounded set of due `scheduled_tasks`
rows, admit typed Session Mailbox work, and return aggregate claimed, admitted,
coalesced, skipped, and wake-failure counters. The Scheduler Job Runtime waits
only for that bounded admission pass, not for Agent work to finish.

## Execution backend

After claiming a due state row, `SchedulerService` submits one `JobRequest` to the shared
application `JobRuntime` with handler key `scheduler.task`. The request carries the task key,
attempt start time, lease owner, manual-trigger flag, an execution key scoped to that database claim,
and an absolute deadline derived from the task timeout. The Scheduler waits for the structured Runtime
outcome before recording success or failure.

The current backend is the AppContext-owned `LocalJobRuntime`. It executes registered handlers with
bounded process-local concurrency, enforces the absolute deadline and cancellation grace, and creates
one task-local DI container for each execution. The `scheduler.task` adapter resolves the current
code-registered definition, reconstructs `TaskContext`, and invokes its async handler. The same Job
Runtime also hosts External Channel ingress through a separate registered handler; Scheduler claims
do not use ingress coalescing or rerun behavior.

If a handler raises while settling inside cancellation grace, Local Job Runtime
keeps the authoritative timeout outcome and records that otherwise-unobserved
handler exception once with origin traceback frames, a static replacement
exception message, and bounded handler/execution identity. Expected cooperative
cancellation remains silent, untrusted exception text is not rendered, and a
handler that outlives grace continues through the separate detached-cleanup
observer.

`job_runtime_backend=temporal` is a recognized configuration value but fails application composition
because that backend is not implemented. Scheduler task handlers do not import Temporal APIs.

## Persistent state

`scheduled_task_states` stores one current-state row per task key.

The row stores:

- task key
- latest status
- next run timestamp
- last started/finished/succeeded/failed timestamps
- failure streak
- latest error code/message
- latest result summary
- lease owner/acquisition/expiration fields
- manual requested timestamp
- created/updated timestamps

There is no attempt history table. Attempt details are emitted through structured logs and the current state row stores only the latest summary. The `file_lifecycle_cleanup` handler also emits a `File lifecycle cleanup completed` log after a successful pass. Its structured fields include the task key, manual-trigger flag, and the cleanup result counters stored in the task summary.

User-defined Task definitions, schedule cursors, occurrence fences, and due leases
are stored separately in `scheduled_tasks`; active occurrence state is stored in
Session-scoped Scheduled Toolkit State. Neither is projected into
`scheduled_task_states`.

## Scheduler loop

On startup, the scheduler ensures that all registered task definitions have state rows.

Registration is one completed database-only operation for all ordered code keys,
including disabled definitions. List, get, and trigger retain a separate completed
registration pass before their own completed read or mutation. An unknown code key
returns no trigger result after registration without submitting a job. The application
retains code-registry access, enable filtering, clock/retry calculation, job construction,
and logging; repositories receive captured keys and scalar/domain facts, not handlers
or database callbacks.

Each loop iteration:

1. Reads registered task definitions from code.
2. Skips definitions that are not enabled by default.
3. Tries to claim due work for each enabled task.
4. Submits only successfully claimed tasks to the shared Job Runtime and waits for their outcomes.
5. Records success or failure and releases the lease.
6. Sleeps until the next poll interval or shutdown signal.

Shutdown stops future polling through an asyncio shutdown event. The scheduler re-raises
`asyncio.CancelledError`. Every other exception in one task lifecycle—including claim, handler,
success/failure state recording, and task-result logging—is isolated to that task and does not stop
later registered tasks in the same scheduler process. If failure-state recording itself fails, the
task's existing lease is left for expiry and a later scheduler loop may reclaim it.

Each iteration captures one application UTC timestamp for its entire ordered claim
loop. Claim completion precedes Job Runtime submit/wait/handler execution. Success or
failure settlement is a separate completed operation afterward. A success-recording
error is not reclassified into failure-recording. A cancelled waiter leaves the committed
claim for existing expiry and does not cancel the shielded accepted LocalJobRuntime job.

## Row lease

The scheduler claims a task with a conditional row update on `scheduled_task_states`.

A claim succeeds only when:

- the task key matches;
- `next_run_at` is due; and
- `lease_until` is null or expired.

A successful claim stores `latest_status=running`, `last_started_at`, `lease_owner`, `leased_at`, and `lease_until`. A failed claim returns no row and the scheduler skips execution for that task.

Only the scheduler instance whose claim update returns a row executes the task. Expired leases can be reclaimed by a later scheduler loop.

Due equality is eligible (`next_run_at <= now`); lease equality is not expired
(`lease_until < now` is required). Application time, the existing timeout plus
30-second lease margin, and the ten-second poll interval are unchanged.

## Success and failure recording

On success, the scheduler stores:

- `latest_status=succeeded`
- `last_finished_at`
- `last_succeeded_at`
- `failure_streak=0`
- cleared latest error fields
- latest result summary
- cleared lease fields
- cleared manual request marker
- next run time based on the task interval

On failure, the scheduler stores:

- `latest_status=failed`
- `last_finished_at`
- `last_failed_at`
- incremented failure streak
- latest error code/message
- cleared result summary
- cleared lease fields
- cleared manual request marker
- next run time based on the task retry policy

Both settlements retain the existing task-key and lease-owner predicate. They add no
attempt-start, expiry, status, or version fence. A normal stale no-row result still
permits the existing application log. Error or cancellation after actual writes rolls
back only that operation; earlier completed registration or claim remains committed.
The nullable result-summary shape and current failure-streak/backoff rules are unchanged.

## Retry policy

Retry policy is part of each task definition.

Supported v1 policies:

- `next_interval`: failure waits until the next normal interval.
- `bounded_backoff`: failure uses exponential backoff bounded by min and max delay.

Success resets the failure streak. Failure increments the persisted streak before the next retry time is calculated.

## File lifecycle cleanup task

`file_lifecycle_cleanup` is the scheduler-owned maintenance task for temporary file resources.
It must not run from AgentWorker run input preparation.

Each pass is bounded and may process:

- due Artifact TTL rows, marking metadata expired and attempting blob deletion;
- due ExchangeFile TTL rows, preserving existing ExchangeFile TTL behavior;
- stale ModelFile pins for terminal runs;
- AgentSession ModelFile GC cursor ranges where `model_file_gc_cursor_event_id` is absent or precedes `model_input_head_event_id`; and
- durable superseded-Agent-avatar cleanup jobs created atomically by committed avatar replacement or removal.

ModelFile GC scans events in `(cursor_event_id, head_event_id]`, extracts FilePart `model_file_id`s,
marks available unpinned ModelFiles deleted, attempts blob deletion, and advances the session GC cursor
only through the processed range. Access denial is metadata-driven; failed blob deletion is logged and
can be retried by a later pass.

Cleanup treats Exchange source provenance and ModelFile Run lineage as descriptive durable metadata,
not User or execution authority. It never chooses a sender, uploader, creator, requester, Workspace
owner, or viewer to decide resource ownership. Historical ModelFiles whose exact Run lineage could not
be resolved remain nullable and are cleaned by their existing Session/lifecycle state rather than a
fabricated Run or User.

The successful task result and completion log include these lifecycle counters:

- `artifacts_expired`, `exchange_files_expired`, and `model_files_deleted` count metadata transitions in the current pass;
- `artifact_blobs_deleted`, `exchange_file_blobs_deleted`, and `model_file_blobs_deleted` count successful object-store deletions by resource type;
- `pending_blob_deletion_attempts` counts selected terminal rows that were already pending blob deletion before the pass began; and
- `blob_delete_failed` counts failed object-store deletion attempts; and
- `avatar_cleanup_attempted`, `avatar_cleanup_completed`, and
  `avatar_cleanup_failed` report the bounded superseded-avatar stage.

The pending snapshot is used only for observability. The actual object-store batch remains bounded at 100 Artifact rows, 100 ExchangeFile rows, and 200 ModelFile rows, with terminal rows selected after the metadata work so existing retry ordering is preserved.

The avatar stage derives one unique opaque claim token per cleanup pass and
claims at most 100 due jobs with five-minute leases. Claiming increments the
attempt count. The handler deletes the immutable snapshot through the avatar
file handler, logs one safe-ID traceback and releases the row into bounded
exponential retry after failure, and deletes the job after successful blob
cleanup only when the exact token still owns it. An expired lease is reclaimable
under a new token, including by a later attempt in the same scheduler process;
the stale token cannot settle the new claim. Agent deletion clears only the
optional diagnostic Agent ID and cannot remove the cleanup snapshot.

## Historical Memory discovery and preparation

`historical_memory_discovery` is enabled by default and runs every five minutes
with a two-minute discovery timeout and bounded one-to-thirty-minute retry.
Admission uses current PostgreSQL authority and active root Session state:
Memory must be enabled, no Run may be ongoing, and latest conversation/Run
activity must be at least six hours old. A never-prepared source must initially
fall within the rolling ten-day window. Pinning and Team-primary status do not
exclude a source.

Each pass admits at most 500 sources and selects at most 25 due Agents. After
the database operations complete, it submits `historical_memory.prepare` work
under `historical-memory:{agent_id}` execution keys with absolute thirty-minute
deadlines. The discovery task waits only for dispatch, not provider preparation.
Admission, due work, and submitted-job counts form its bounded result summary.

Preparation runs in application Job Runtime, coalescing same-Agent work within
one process. A job attempts at most ten source operations; its handler defaults
to 12 of the application's 16 concurrency slots. Registered
`historical_memory.consolidate` handlers use two more slots, leaving combined
Memory capacity at 14 and two ordinary slots. Configured preparation capacity
must obey the combined limit. Every worker replica owns its local capacity;
these limits are not a deployment-wide spend ceiling.
Process-local coalescing does not promise cross-process exactly-once preparation model
calls. Durable source progress plus later discovery recover interrupted or
unaccepted work without a persistent Runtime queue or Redis dependency.

Preparation uses the Agent Lightweight chain and rechecks enablement,
source lifecycle, and current access before publication. Retry/completion for
admitted sources and retention of prepared summaries are not bounded by the
initial ten-day admission window. Unchanged content is not repeatedly prepared
merely because time passes; later activity can permit a fresh inactive
preparation.

Consolidation discovery reuses this five-minute cadence for exact Team/personal
units and due recovery. Obsolete metadata retirement runs inside the claimed
attempt before model preparation, not in discovery before dispatch. Short
PostgreSQL leases and owner generations, not local coalescing or Redis, establish
one active consolidation owner per unit. Jobs use ten-minute absolute attempts,
renew 120-second leases every 30 seconds, and preserve exact pending work across
productive finite slices. Productive progress requeues without failure delay;
failures/no progress use one-minute exponential backoff capped at six hours.
Fenced periodic cleanup preserves active owners, unfinished passes and snapshot-
referenced publications while collecting eligible private payloads.
No Saved Memory is created or mutated. See
[`memory.md`](../domain/memory.md) for retry, source, and publication contracts.

## External account OAuth attempt cleanup task

`external_account_oauth_cleanup` runs hourly with a two-minute timeout and bounded
five-minute-to-one-hour retry backoff. Each pass deletes at most 500 terminal or
expired OAuth attempts whose ten-minute attempt lifetime has ended and whose rows
are older than the 24-hour retention window. The result reports the bounded
deleted-attempt count.

Attempt expiry is enforced synchronously by every OAuth operation. This scheduled
task is storage reclamation only: delayed execution, lease recovery, Redis loss, or
a failed cleanup pass cannot make an expired, claimed, completed, or failed attempt
usable again.

## Session automatic archive task

`session_auto_archive` runs every five minutes with a ten-minute task timeout and bounded
one-to-thirty-minute scheduler retry. Each pass reads at most 100 oldest active non-primary unpinned
root Session candidates, then delegates each candidate to the normal Session archive transition. That
transition locks the full tree and revalidates dynamic Agent TTL eligibility, pin state, latest
activity across descendants, and running work before archive side effects begin, so a stale candidate
read cannot archive a newly active or newly pinned tree. The task result reports `scanned`,
`archived`, and `skipped`; skipped candidates are expected races or no-longer-eligible roots rather
than batch failure.

## Archived-session retention recalculation task

`archived_session_retention_recalculation` runs every minute with a two-minute task timeout and
bounded one-to-thirty-minute scheduler retry. It claims at most one durable retention application
whose own lease is absent or expired, then recalculates at most 100 archived roots in stable ID order.
The application records its target settings revision, target whole-day value, cursor, cumulative
impact counters, attempt count, lease, next retry time, bounded user-safe error summary, and terminal
timestamps.

For each root that has not entered purge fencing, the handler replaces the immutable archive snapshot
with the application revision, derives the deadline from the original `archived_at`, and creates,
reschedules, or cancels unstarted purge work. A null target means Unlimited and clears the deadline.
A finite target schedules every affected root; an already-past deadline becomes eligible for the
separate purge task without being deleted in this handler. Roots whose purge fence already started are
skipped and remain irreversible. Batch failure releases the durable application into exponential retry
wait capped at 30 minutes; successful batches advance the cursor until the application is completed.

## Archived-session purge task

`archived_session_purge` runs every five minutes with a ten-minute task timeout and bounded
one-to-thirty-minute scheduler retry. Before claiming work it cancels at most 100 stale unstarted jobs
whose root status, deadline, or policy revision no longer matches the job. It then claims and advances
at most 100 due purge jobs with individual 15-minute durable leases, stopping before it claims another
job when the scheduler deadline has less than 30 seconds remaining. Claiming starts the irreversible
purge fence; restore is rejected from that point even if cleanup later retries.

One root purge failure records the durable job retry and a structured exception log, then the same
scheduler pass continues with the next due root. Active runs likewise schedule that root for retry
without blocking later roots. Cancellation, failure to persist durable retry state, or other
batch-level infrastructure failure still fails the scheduler task.
The claim transaction materializes a participant snapshot only when the job has no
existing snapshot. It validates stored keys, policy versions, and dependency
closure before lifecycle fencing or cleanup begins. An application-level snapshot
validation failure commits the job lease, records a durable per-job retry, and
preserves later-job isolation. The retry records the affected participant when
known and the pre-execution participant stage. Database transaction or commit
failures remain batch-level infrastructure failures.
The persisted `session.git-worktrees@1` key is a database-only compatibility
participant. Existing jobs retry and checkpoint it through the same durable phase
workflow without contacting a Runtime or checking physical Git state.

The handler locks the complete root tree, increments owner generations, records stop intent, emits
broker stop signals, and waits for active runs through durable retry rather than deleting around them.
After no active run remains, it removes broker state, marks subtree file resources terminal, deletes
their external blobs, revalidates required cleanup state, deletes file metadata, and finally deletes
worktree allocation rows and the root database subtree. It never inspects or mutates physical Git
state. Only then does the content-free purge job tombstone become completed. Required external
cleanup failure or lost ownership keeps metadata and durable retry state instead of allowing a
cascade to hide unfinished work.

## Agent decommission task

`agent_decommission` advances content-free durable Agent decommission jobs with per-job leases,
generation fencing, bounded retry backoff, and failure isolation. It retires eligible Agent root
sessions through the session lifecycle but never directly deletes an AgentSession or applies a
request-specific purge deadline. After retention purge removes retired roots, it requests internal
Provider terminal deletion for each Agent Runtime and waits for the matching durable generation
acknowledgement. Only then may the finalizer remove remaining Agent-owned resources and the Agent
row. One job retry does not prevent later due jobs from advancing; completed jobs remain tombstones.

## CLI operations

The scheduler CLI exposes:

- `run`: start the scheduler loop.
- `list`: list current state for all registered tasks.
- `status <task-key>`: show current state for one task.
- `trigger <task-key>`: request manual execution.

Manual trigger does not execute handlers directly. It validates that the task key exists in the code registry and updates current state so `next_run_at` and `manual_requested_at` are set to now. The scheduler loop later performs the normal row lease claim and execution flow.

## Out of scope

The periodic execution flow does not provide:

- direct execution of user Scheduled Task objectives inside the Scheduler role;
- Admin API or Admin UI controls;
- DB-defined schedules or runtime schedule overrides for the code-owned
  maintenance registry;
- attempt history tables;
- Temporal workflows or activities;
- an independently scheduled model-catalog source sync; source collection is part of
  the existing system projection task.

## Changelog

- **2026-10-04** (spec_version 26) — Promoted consolidation discovery/recovery/
  cleanup and PostgreSQL ownership, preparation12/consolidation2 combined14
  local capacity and per-replica scaling semantics.

- **2026-10-03** (spec_version 25) — Kept source collection in the existing
  system projection task while replacing revision publication with current rows,
  normalized prices, and current synchronization facts.
- **2026-10-02** (spec_version 24) — Completed Scheduler registration/read/trigger/
  claim/settlement transaction ownership while preserving clock, lease, Job Runtime,
  normal stale outcomes, and cancellation/error ordering.
- **2026-10-02** (spec_version 23) — Added enabled five-minute Historical
  discovery, bounded rolling admission, and separate coalesced per-Agent
  preparation with durable recovery and reserved background capacity.
- **2026-10-01** (spec_version 22) — Removed the temporary integration
  reprojection task after cleanup validated generic provenance on every current
  conversation catalog.
- **2026-10-01** (spec_version 21) — Made the existing system catalog task
  publish generic metadata authority and added bounded, network-free integration
  catalog reprojection from stored current entries.
- **2026-09-13** (spec_version 20) — Replaced legacy origin/candidate proof
  reclamation with the hourly `external_account_oauth_cleanup` task for retained
  OAuth attempts.

- **2026-09-12** — v19. Added bounded hourly reclamation of expired external-account
  proof rows while keeping synchronous expiry checks as correctness authority.
- **2026-09-06** — v18. Added Runtime Control to local devserver composition and
  made it ready before Worker dependency resolution.
- **2026-08-18** — v16. Added durable scheduler-owned cleanup for avatars
  superseded by committed Agent replacement/removal, plus exact observation of
  Local Job Runtime handler failures that settle during cancellation grace.
- **2026-08-31** — v17. Replaced numeric ModelFile GC order ranges with event-ID head
  and cursor ranges.
- **2026-08-17** — v15. Removed the shared Job Runtime diagnostics introduced in
  v13 while preserving the current Scheduled Task dispatcher behavior.
- **2026-08-17** — v14. Added the code-owned user Scheduled Task dispatcher to the
  existing Scheduler role while keeping product `scheduled_tasks` and cycle
  Toolkit State separate from maintenance `scheduled_task_states`.
- **2026-08-16** — v13. Added the shared Job Runtime's content-free structured
  handler-failure and stage-specific absolute-deadline diagnostics.
- **2026-08-15** — v12. Replaced the removed `TaskExecutor` description with the shared
  Job Runtime execution path, completed the registered task inventory, and added current Job Runtime
  and lifecycle-service authority paths. Removed obsolete ArgoCD manifest references.
- **2026-07-24** — v10. Clarified that lifecycle cleanup treats typed file provenance and nullable
  unresolved ModelFile Run lineage as metadata, never as User or execution authority.
- **2026-07-26** — v11. Added the bounded five-minute `session_auto_archive` task and its
  lock-and-recheck eligibility behavior.
- **2026-07-23** — v9. Made existing Git worktree participant retries database-only so they converge without Runtime availability.
- **2026-07-19** — v4. Added the durable archived-session retention recalculation and purge tasks, including intervals, leases, bounded batching, stale-job reconciliation, fencing, retry, and cleanup ordering.
- **2026-07-21** — v5. Isolated ordinary scheduler task lifecycle failures so one task cannot terminate the scheduler process; cancellation remains a scheduler shutdown signal.
- **2026-07-21** — v6. Isolated per-root purge failures so a bounded scheduler pass logs and retries the failed root before continuing with later due roots.
- **2026-07-21** — v7. Added durable Agent decommission scheduling with retention-purge and Runtime-acknowledgement finalization gates.
- **2026-07-22** — v8. Kept participant snapshot validation failures inside per-root retry isolation while leaving database transaction failures at the scheduler boundary.
