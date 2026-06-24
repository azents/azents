---
title: "ADR-0068: Periodic Execution Infrastructure"
created: 2026-06-20
tags: [architecture, backend, engine, infra]
---

# ADR-0068: Periodic Execution Infrastructure

## Status

Accepted.

## Context

Azents needs system-owned periodic execution for work such as model catalog source sync, projection refresh, cleanup, reconciliation, and future maintenance tasks. The immediate model catalog design assumes a periodic execution infrastructure, but that infrastructure is separate from model catalog semantics.

Earlier discussions considered Temporal. Temporal is a strong fit for durable background execution, but it is not adopted as the first implementation for these reasons:

- Temporal background task execution is clean, but Temporal scheduling is not the most intuitive fit for the current system jobs.
- Azents devserver is a standalone all-in-one local server and should not require Temporal.
- If Temporal becomes optional in distributed mode, Azents still needs an abstraction that hides Temporal from product/domain code so devserver can keep the same task contract.
- Current planned jobs are lightweight enough that Temporal would be too heavy as the first dependency.
- The design should still leave a path for heavier durable work later.

Distributed mode is already live. Production roles are separated into API, admin, runtime-control, worker, and supporting components. The existing `AgentWorker` owns agent session execution and has worker-internal recovery loops such as stuck session recovery. General system periodic jobs must not be added to `AgentWorker`.

This ADR defines a lightweight system periodic execution infrastructure. It is not the user/agent-facing scheduled task product described by ADR-0023. User-defined schedules, cron/timezone UX, notification delivery, and agent-created scheduled work remain separate product scope.

## Decision

### ADR-0068-D1. Introduce a separate scheduler role

Periodic execution runs in a separate scheduler entrypoint and production Deployment.

The scheduler must not be implemented inside `AgentWorker`. Worker-internal loops such as stuck session recovery remain worker responsibilities and are not migrated by this ADR.

Devserver runs the scheduler together with Public API, Admin API, and Worker for local all-in-one reproduction. This is a local packaging convenience and does not change production role boundaries.

### ADR-0068-D2. Separate scheduling from execution through a TaskExecutor interface

The scheduler owns due-job discovery, lease claiming, attempt lifecycle, retry scheduling, and state recording.

Actual task execution is delegated to a `TaskExecutor` interface.

The v1 executor is local direct execution: it invokes the registered handler in the scheduler process. Future executors may dispatch to Temporal, a dedicated queue, or another durable backend without changing task definitions.

### ADR-0068-D3. Keep schedule definitions in code registry

System periodic task definitions live in code, not in DB.

A `ScheduledTaskDefinition` includes at least:

- task key
- interval
- timeout
- retry policy
- handler reference
- enabled default

The DB stores runtime state only. DB-defined schedules and DB overrides are out of scope for v1. If runtime override becomes necessary, code defaults plus DB overrides can be designed later.

### ADR-0068-D4. Store current scheduler state only

Scheduler DB state is current-only per task key.

The scheduler stores latest/current state such as:

- task key
- latest status
- last started time
- last finished time
- last succeeded time
- last failed time
- next run time
- failure streak
- latest error code/message
- lease owner
- lease acquisition time
- lease expiration time

The scheduler does not store attempt history in v1. Attempt-level observability is provided by structured logs and Sentry/metrics where appropriate. Historical audit or attempt tables can be designed later if needed.

### ADR-0068-D5. Use Postgres row lease for concurrency control

The `scheduled_task_states` row includes lease fields such as `lease_owner`, `leased_at`, and `lease_until`.

Scheduler instances claim due work with a conditional update that requires the task to be due and the lease to be absent or expired. Only the instance that updates the row executes the task.

Task concurrency is one execution per task key. Rollout overlap, multiple scheduler replicas, and devserver/production collisions are controlled by the same row lease.

A stuck lease recovers when `lease_until` expires. v1 assumes tasks finish within their timeout and does not require lease heartbeat/extension.

### ADR-0068-D6. Use task-definition retry policy

Retry behavior is part of `ScheduledTaskDefinition`.

v1 supports two retry policy types:

- `next_interval`: after failure, wait for the next regular interval.
- `bounded_backoff`: after failure, schedule a bounded backoff using failure streak and configured min/max delay.

The state row stores `failure_streak`, latest failure summary, and `next_run_at` so retry state survives scheduler restart.

### ADR-0068-D7. Provide manual trigger through CLI only

v1 manual operations are CLI-only.

CLI trigger does not execute handlers directly. It requests execution by updating scheduler state, such as setting `next_run_at` to now or recording a manual trigger marker. The scheduler loop still claims the row lease and executes the task.

Admin API, admin UI, arbitrary manual payloads, and user-triggered system jobs are out of scope for v1.

### ADR-0068-D8. Devserver runs scheduler by default

Devserver starts the scheduler by default as part of its all-in-one local process.

Production uses a separate scheduler entrypoint/Deployment. Devserver co-location is only for local reproduction and does not make the scheduler an API or worker responsibility.

### ADR-0068-D9. Expose v1 observability through CLI, logs, and current state

v1 operations surface is CLI status commands plus structured logs.

CLI commands should include at least:

- list registered tasks and current state
- show status for a task key
- trigger a task key manually

Admin read API and admin UI are out of scope for v1.

### ADR-0068-D10. Use no-op heartbeat as first consumer

The first scheduler consumer is a no-op heartbeat task.

The heartbeat validates scheduler entrypoint wiring, code registry, current state row, row lease, retry/state update path, CLI list/status/trigger, devserver integration, and production Deployment wiring without external network dependencies.

LiteLLM source snapshot sync and model catalog work are implemented in later phases after the scheduler infrastructure is in place.

### ADR-0068-D11. Treat Temporal as a future executor candidate only

Temporal is not part of v1.

Task handlers must not import Temporal APIs. v1 does not introduce Temporal workflow/activity/signal/query/heartbeat concepts. The only Temporal-related requirement is preserving a `TaskExecutor` boundary so future heavy durable tasks can introduce a Temporal executor through a separate design.

## Consequences

### Positive

- Production gets a dedicated scheduler role instead of mixing system jobs into AgentWorker.
- Devserver keeps standalone all-in-one behavior without Temporal.
- Scheduler core is lightweight and can be verified with a no-op heartbeat before model catalog work.
- Postgres row lease provides safe rollout and multi-replica concurrency control.
- Code registry keeps system job definitions reviewable and avoids DB-defined job drift.
- `TaskExecutor` boundary leaves room for future Temporal or queue-backed execution.

### Negative / Trade-offs

- v1 has no admin API/UI for scheduler operations.
- v1 has no attempt history table; historical debugging relies on logs/Sentry.
- Schedule changes require deploy because definitions live in code.
- Local direct execution means heavy durable tasks still need a later backend design.
- A scheduler Deployment and devserver wiring must be added before first real system job.

## Alternatives

### Put periodic execution inside AgentWorker

Rejected. AgentWorker owns agent session execution. System periodic jobs such as catalog source sync should not share worker role boundaries or resources. Devserver can co-run components locally, but production role boundaries must remain separate.

### Use Temporal first

Rejected for v1. Temporal may be valuable for future heavy durable work, but it is too heavy for current lightweight system jobs, and devserver must not depend on Temporal.

### Use Kubernetes CronJob as the primary scheduler

Rejected for v1. CronJob would make local/devserver behavior diverge from production and would split scheduler state, lease, retry, and CLI operations across Kubernetes and application state.

### Store schedules in DB

Rejected for v1. This infrastructure is for system periodic jobs, not user-defined schedules. Code registry is simpler, safer, and easier to review.

### Store full attempt history

Rejected for v1. Current state plus structured logs is enough for initial system jobs. Attempt history can be added later if operations require it.

### Start with LiteLLM source sync as the first consumer

Rejected. Scheduler infrastructure should be validated before adding external network and model catalog source semantics. LiteLLM source sync is the next phase after heartbeat proves the scheduler path.

## Related Documents

- [ADR-0023: Scheduled Tasks Discussion](./0023-scheduled-tasks.md)
- [ADR-0067: Model Catalog Projection and Sync](./0067-model-catalog-projection-sync.md)
