---
title: "Periodic execution"
created: 2026-06-20
tags: [backend, engine, infra]
---

# Periodic execution

Scheduler admission for maintenance, Scheduled Tasks and Routine source checks with separate authorities.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Scheduled Tasks](../domain/scheduled-task.md)
- [Session Routines](../domain/routine.md)
- [Memory](../domain/memory.md)
- [Agent deletion](../domain/agent-deletion.md)

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
`compacted_event_cleanup`,
`session_auto_archive`, `agent_decommission`, `agent_runtime_removal`, `owner_lifecycle`,
`file_lifecycle_cleanup`, `external_account_oauth_cleanup`,
`historical_memory_discovery`, plus the user Scheduled
Task dispatcher definition.
`scheduler_heartbeat` is a no-op heartbeat that returns a small execution
summary and has no external network dependency.

`compacted_event_cleanup` runs every five minutes with a two-minute timeout and
bounded retry backoff from one to thirty minutes. It deletes at most 1,000 expired
pre-head events per pass, using first compaction displacement age and the current
independent lifecycle retention setting. Unlimited (the default) skips deletion.
The pass holds a shared settings lock, locks eligible event rows with skip-locked,
waits for the ModelFile GC cursor and protects pending/running Run input
references. Its summary reports `deleted_count`, `limit_reached` and `unlimited`.

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

`ScheduledTaskDispatcher` sequences completed database-only
`ScheduledTaskDispatchRepository` claim and admission operations. Claims retain
the exact lease owner, token, and expiry fence. Admission atomically writes the
cycle snapshot, typed Mailbox trigger, Session recovery wake state, and Task
cursor; a lost final claim fence rolls back all admission writes. Each operation
closes its database scope before returning. Broker wake follows admission commit,
and a wake failure increments the existing counter without undoing admitted work.
The injected pure clock retains expiry checks during admission; provider, broker,
and Runtime I/O remain outside the repository transaction.

Management and provider-control services likewise call completed owner operations.
Independent management list, get, and current-cycle reads use native PostgreSQL
read-only scopes. Management mutations preserve Session, Agent, and Binding
authority checks followed by the shared Mailbox → cycle → Task lock order.
Provider controls authorize the claimed actor and Binding and mutate the Task in
one atomic owner operation. Registration and deletion presentation follows
completed create and delete operations; replacement retains its existing
no-provider-effect path. Repository-only definition composition shares the
transaction without exposing live sessions to services. Detached management and
control contracts are defined in their corresponding core modules.

## Execution backend

After claiming a due state row, `SchedulerService` submits one `JobRequest` to the shared
application `JobRuntime` with handler key `scheduler.task`. The request carries the task key,
attempt start time, lease owner, manual-trigger flag, an execution key scoped to that database claim,
and an absolute deadline derived from the task timeout. The Scheduler waits for the structured Runtime
outcome before recording success or failure.

The handler returns a validated `TaskResult` envelope with opaque `summary` and
required nullable timezone-aware `next_run_at`. Null retains completion time plus
the definition interval. An explicit time controls the next successful
execution; already-past times become eligible at completion and are picked up by
normal polling. Invalid result envelopes fail the task. Existing failure retry
policy, database claim identity and lease recovery are unchanged.

The current backend is the AppContext-owned `LocalJobRuntime`. It executes registered handlers with
bounded process-local concurrency, enforces the absolute deadline and cancellation grace, and creates
one task-local DI container for each execution. The `scheduler.task` adapter resolves the current
code-registered definition, reconstructs `TaskContext`, and invokes its async handler. The same Job
Runtime also hosts External Channel ingress through a separate registered handler; Scheduler claims
do not use ingress coalescing or rerun behavior.

Local Job Runtime owns one terminal ERROR observation per execution attempt.
Uncaught handler/startup failures and elapsed cutoffs retain origin traceback
frames with static replacement exception text and content-free handler/execution
identity. The Runtime deadline path logs even when it wins an inner supervisor's
timeout race; cooperative cancellation supplies handler frames when available.
External shutdown cancellation before a deadline remains non-error cancellation.
The first failure/outcome survives a subsequent container cleanup fault.

Cancellation-grace, detached-handler and cleanup faults after the terminal
observation are sanitized WARNING diagnostics, not duplicate terminal ERRORs.
A handler that outlives grace continues through the separately owned
detached-cleanup observer. Untrusted exception text, context and notes are never
rendered in these observations.

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

Five-minute discovery admits never-prepared eligible active Conversation roots
whose latest activity is six hours to ten days old, with no ongoing Run. Each
pass admits at most 500 sources and routes at most 25 due Agents. Admitted
retry/completion and retained summaries can outlive the initial ten-day window.
Stage 1 `historical_memory.prepare` remains a registered Job Runtime handler,
coalesced per Agent, with ten source operations and a thirty-minute request
deadline. Its local preparation concurrency defaults to 12, configurable 1–12.
There is no separate two-slot consolidation handler or combined 14-slot Memory
reservation. Prepared-source progress and rediscovery recover interrupted work;
process coalescing does not prove cross-process exactly-once provider calls.

Preparation uses captured Lightweight candidates, scope/source permission and
ordinary provider contracts. It publishes summaries only after current access,
source lifecycle and enablement checks. Source summaries stay distinct from
Saved entries and from the current integrated scope result.

Integration discovery observes pending same-Agent Team/personal work and durably
associates it with an internal common Session. After DB admission, it publishes
`SessionWakeUp` routing to the ordinary Worker. The Session owner generation,
broker lock, heartbeat, Run and canonical Event lifecycle are the only execution
owner. The Scheduler/Job Runtime does not run a private model/tool host.

Fresh admission snapshots `historical_memory_execution` max turns and timeout
(defaults unlimited logical turns and 600 seconds) into a policy and absolute
deadline. Owner takeover creates a clean successor Session using the existing
deadline, policy and consumed turns, not a new budget. Common Worker stop/shutdown
supervision and physical-send owner/cancellation admission apply. Candidate
quota handoff stays on the captured Lightweight chain. Model operations close as
`FOREGROUND` through the common Run lifecycle; that kind does not imply Main
model selection. Failed/unaccepted work is released for discovery with unit
backoff starting at one minute and capped at six hours; accepted work retains its
original outcome even when secondary close/archive/dispatch follow-up fails.

Provisioned input files contain only currently eligible prepared summaries.
The Agent writes a fresh Markdown artifact and explicitly calls `submit_memory`
with its authored execution-file path. Format/size feedback and final-only output
continue the same execution. Acceptance atomically stores the current scope
result, settles associated supplied work and completes the common Run; late or
unassociated changes remain pending. No draft coverage, original transcript,
source-version/dependency ledger or previous integrated prose is supplied.

Operator/testenv sampling prepares sources and dispatches this real Worker route.
Its report contains `consolidation_dispatched`, not a synchronous publication
count or simulated integration success. Current-result observation is a separate
read after dispatch. Terminal internal Sessions archive via common lifecycle,
retain audit/files until retention purge, and retain current result/original
acceptance scalars after audit purge. See [`memory.md`](../domain/memory.md) and
[`conversation.md`](../domain/conversation.md) for current access and lifecycle.

## External account OAuth attempt cleanup task

`external_account_oauth_cleanup` runs hourly with a two-minute timeout and bounded
five-minute-to-one-hour retry backoff. Each pass deletes at most 500 OAuth
attempts whose `created_at` or `expires_at` is at or before the 24-hour retention
cutoff, preserving the existing OR predicate. The ten-minute attempt lifetime
continues to control synchronous OAuth expiry independently. The result reports
the bounded deleted-attempt count.

Attempt expiry is enforced synchronously by every OAuth operation. This scheduled
task is storage reclamation only: delayed execution, lease recovery, Redis loss, or
a failed cleanup pass cannot make an expired, claimed, completed, or failed attempt
usable again.

Expired-attempt housekeeping performs a bounded conditional DELETE using the
existing cutoff/expiry predicates rather than locking candidates before
selection. It is not callback claim or one-time authentication consumption;
those operations retain their exact attempt and revocation guards.

## Session automatic archive task

`session_auto_archive` runs every five minutes with a ten-minute task timeout and bounded
one-to-thirty-minute scheduler retry. Each pass reads at most 100 oldest active non-primary unpinned
root Session candidates, then delegates each candidate to the normal Session archive transition. That
transition locks the full tree and revalidates dynamic Agent TTL eligibility, pin state, latest
activity across descendants, and running work before archive side effects begin, so a stale candidate
read cannot archive a newly active or newly pinned tree. The task result reports `scanned`,
`archived`, and `skipped`; skipped candidates are expected races or no-longer-eligible roots rather
than batch failure.

## Archive and file maintenance database ownership

Archive retention, purge, and file cleanup services sequence completed repository
operations. Retention revision replacement and optional application creation share one
transaction; recalculation batch effects and cursor advancement remain atomic under
the exact durable application lease. First-use settings initialization remains a
write operation, while independent application/impact observations use native
PostgreSQL read-only scopes.

Purge claim and immutable participant materialization commit together. Root-tree
fencing and stop requests complete before broker signals. Participant attempts,
failure attribution, and checkpoints each finish their database scope before the
service runs the participant. Database-only Scheduled and External Channel
participants are composed below services, including restrictive final verification
and root deletion in the same finalization transaction. Pure participant policy
validation and external participant ordering remain service-side. Broker, blob,
provider and Runtime I/O never run inside those database scopes.

File cleanup captures its preexisting terminal-blob IDs before current expiration
and GC mutations. Independent metadata/transcript reads use native read-only scopes;
terminal marking and cursor advancement preserve their existing conditional writes.
Avatar claim and post-delete settlement use the exact cleanup lease. Object deletion
runs after preparation closes and before its completed metadata settlement.

## Archived-session retention recalculation task

Retention targets are common lifecycle roots (`lifecycle_root_session_id` is
null), including profile-free internal Sessions. No public root-kind or
`SessionAgent` join is required. Conversation descendants remain grouped with
their common root, and the existing finite/Unlimited policy is unchanged.

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

The handler locks the complete common lifecycle target, increments owner generations, records stop intent, emits
broker stop signals, and waits for active runs through durable retry rather than deleting around them.
After no active run remains, it removes broker state, marks subtree file resources terminal, deletes
their external blobs, revalidates required cleanup state, deletes file metadata, and finally deletes
worktree allocation rows and the common Session group, including a singleton
internal Session without a participant tree. Canonical current execution files
and Conversation profiles are registered database children; their presence does
not create another purger. It never inspects or mutates physical Git
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

## Routine Source Dispatch

The existing Scheduler also performs bounded source-only
[Routine admission](../domain/routine.md). It scans eligible active Session owners,
coalesces source evidence, enqueues an internal judgment action and sends an
ordinary payload-free Session wake-up. It never calls the judgment model or
executes Routine work. Code-job leases remain code-job infrastructure, not a
Routine judgment owner or domain retry contract.

The supported `manual` source contributes candidates at regular eligible checks;
it is not a manual-run endpoint. Tick cadence and minimum action delay remain
30-minute boundaries. Settled judgment advances the checking checkpoint, so the
next opportunity follows judge completion rather than the preceding source tick
or eventual ordinary-work completion. No-action and failed judgments leave the
last-action reference unchanged. The dispatcher returns the earliest eligible
Session time through the common Scheduler's explicit next-time result, capped at
the regular discovery interval. An early scan waits the remaining delay rather
than another full interval. Normal scheduler polling still applies.
Empty source sets and ongoing incomplete work do not create new work.
Testenv-only exact-aware dispatch delegates to the same service and returns
admission counts; it does not manufacture judgment or completion.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/scheduler`](../../../../python/apps/azents/src/azents/scheduler)
- [`python/apps/azents/src/azents/job_runtime`](../../../../python/apps/azents/src/azents/job_runtime)
- [`python/apps/azents/src/azents/services/file_lifecycle_cleanup.py`](../../../../python/apps/azents/src/azents/services/file_lifecycle_cleanup.py)
