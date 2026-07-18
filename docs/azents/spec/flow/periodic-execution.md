---
title: "Periodic Execution Flow Spec"
created: 2026-06-20
tags: [backend, engine, infra]
spec_type: flow
code_paths:
  - python/apps/azents/src/azents/scheduler/types.py
  - python/apps/azents/src/azents/scheduler/registry.py
  - python/apps/azents/src/azents/scheduler/executor.py
  - python/apps/azents/src/azents/scheduler/service.py
  - python/apps/azents/src/azents/services/file_lifecycle_cleanup.py
  - python/apps/azents/src/azents/repos/scheduled_task_state/__init__.py
  - python/apps/azents/src/azents/repos/scheduled_task_state/data.py
  - python/apps/azents/src/azents/rdb/models/scheduled_task_state.py
  - python/apps/azents/src/cli/scheduler.py
  - python/apps/azents/src/cli/devserver.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/c7b64368f3a1_add_scheduled_task_states.py
  - python/apps/azents/bin/scheduler.sh
  - infra/argocd/azents-server/base/scheduler-deployment.yaml
  - infra/argocd/azents-server/base/scheduler-pdb.yaml
  - infra/charts/azents/templates/server/scheduler-deployment.yaml.tpl
  - infra/charts/azents/templates/server/scheduler-pdb.yaml.tpl
last_verified_at: 2026-07-18
spec_version: 3
---

# Periodic Execution Flow Spec

Azents periodic execution is the system-owned scheduler flow for lightweight maintenance and synchronization jobs. It is separate from user/agent-facing scheduled tasks.

## Runtime roles

Production runs periodic execution through a dedicated scheduler role. The production entrypoint is `bin/scheduler.sh`, which applies the RDB revision from `db-schemas/rdb/revision` when needed and then starts `src/cli/scheduler.py run`.

Production manifests define a separate scheduler Deployment and PodDisruptionBudget for ArgoCD and Helm chart consumers. The scheduler uses the server image and server environment sources, but it is not the AgentWorker.

Devserver runs Public API, Admin API, AgentWorker, and Scheduler in one local process. This is local packaging only; it does not collapse the production scheduler role into AgentWorker.

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

The database does not store task definitions or schedule overrides. It stores current runtime state only.

Registered tasks include `scheduler_heartbeat`, model catalog projection, and `file_lifecycle_cleanup`. `scheduler_heartbeat` is a no-op heartbeat that returns a small execution summary and has no external network dependency.

## Execution backend

Scheduler execution is abstracted by `TaskExecutor`.

The v1 executor is `LocalTaskExecutor`, which calls the registered handler in the scheduler process with an asyncio timeout based on the task definition timeout.

Scheduler task handlers do not import Temporal APIs. A future durable execution backend would be added behind the `TaskExecutor` boundary.

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

## Scheduler loop

On startup, the scheduler ensures that all registered task definitions have state rows.

Each loop iteration:

1. Reads registered task definitions from code.
2. Skips definitions that are not enabled by default.
3. Tries to claim due work for each enabled task.
4. Executes only tasks whose row lease claim succeeds.
5. Records success or failure and releases the lease.
6. Sleeps until the next poll interval or shutdown signal.

Shutdown stops future polling through an asyncio shutdown event. The scheduler re-raises `asyncio.CancelledError` and records ordinary handler exceptions as task failures.

## Row lease

The scheduler claims a task with a conditional row update on `scheduled_task_states`.

A claim succeeds only when:

- the task key matches;
- `next_run_at` is due; and
- `lease_until` is null or expired.

A successful claim stores `latest_status=running`, `last_started_at`, `lease_owner`, `leased_at`, and `lease_until`. A failed claim returns no row and the scheduler skips execution for that task.

Only the scheduler instance whose claim update returns a row executes the task. Expired leases can be reclaimed by a later scheduler loop.

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
- AgentSession ModelFile GC cursor ranges where `model_file_gc_cursor_model_order` lags behind `model_input_head_model_order`.

ModelFile GC scans events in `(cursor_order, head_order]`, extracts FilePart `model_file_id`s,
marks available unpinned ModelFiles deleted, attempts blob deletion, and advances the session GC cursor
only through the processed range. Access denial is metadata-driven; failed blob deletion is logged and
can be retried by a later pass.

The successful task result and completion log include these lifecycle counters:

- `artifacts_expired`, `exchange_files_expired`, and `model_files_deleted` count metadata transitions in the current pass;
- `artifact_blobs_deleted`, `exchange_file_blobs_deleted`, and `model_file_blobs_deleted` count successful object-store deletions by resource type;
- `pending_blob_deletion_attempts` counts selected terminal rows that were already pending blob deletion before the pass began; and
- `blob_delete_failed` counts failed object-store deletion attempts.

The pending snapshot is used only for observability. The actual object-store batch remains bounded at 100 Artifact rows, 100 ExchangeFile rows, and 200 ModelFile rows, with terminal rows selected after the metadata work so existing retry ordering is preserved.

## CLI operations

The scheduler CLI exposes:

- `run`: start the scheduler loop.
- `list`: list current state for all registered tasks.
- `status <task-key>`: show current state for one task.
- `trigger <task-key>`: request manual execution.

Manual trigger does not execute handlers directly. It validates that the task key exists in the code registry and updates current state so `next_run_at` and `manual_requested_at` are set to now. The scheduler loop later performs the normal row lease claim and execution flow.

## Out of scope

The periodic execution flow does not provide:

- user-defined scheduled tasks;
- Admin API or Admin UI controls;
- DB-defined schedules or runtime schedule overrides;
- attempt history tables;
- Temporal workflows or activities;
- external model catalog source sync by itself.

Model catalog source sync is a later consumer of this scheduler.
