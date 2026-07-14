---
title: "Run Resume"
created: 2026-05-10
tags: [backend, engine]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation]
code_paths:
  - python/apps/azents/src/azents/broker/redis.py
  - python/apps/azents/src/azents/broker/types.py
  - python/apps/azents/src/azents/worker/worker.py
  - python/apps/azents/src/azents/services/agent_session_input.py
  - python/apps/azents/src/azents/services/session_git_worktree/**
  - python/apps/azents/src/azents/services/action_execution.py
  - python/apps/azents/src/azents/repos/action_execution/**
  - python/apps/azents/src/azents/repos/agent_run/**
  - python/apps/azents/src/azents/repos/agent_execution/**
  - python/apps/azents/src/azents/repos/agent_runtime/**
  - python/apps/azents/src/azents/engine/run/contracts.py
  - python/apps/azents/src/azents/engine/events/**
  - python/apps/azents/src/azents/engine/run/types.py
  - python/apps/azents/src/azents/engine/run/errors.py
  - python/apps/azents/src/azents/worker/session/**
last_verified_at: 2026-07-14
spec_version: 21
---

# Run Resume

Run resume handles worker shutdown, process crash, stale running state, and interrupted tool calls.
The event runtime resumes from durable transcript and `agent_runs`, not SDK serialized
`RunState`.

## Resume Sources

| Source | Detection | Behavior |
| --- | --- | --- |
| Broker wake-up | New session wake-up signal | Live sticky owner receives the wake-up directly; otherwise a worker can take over after owner heartbeat expiry |
| Broker redelivery | Unacked session wake-up signal | Another worker receives and resumes from durable DB state |
| Stale session activity | Worker recovery scan of `agent_sessions.run_state` | Worker enqueues a wake-up signal for the affected session |
| Active event run | pending/running `agent_runs`, resolved inference provenance, phase, active tools, and retry state | Runtime preserves the run/input boundary, resumes from an activated snapshot, and repairs missing interrupted results |
| Pending tool call | Event transcript has call without result | Runtime appends one deterministic cancelled result without executing the handler |
| Leftover operation action | Session has an active buffer-keyed action execution at a new processing boundary | Worker records one cancelled durable snapshot and deletes the live execution before admitting new work; it never invokes the stale handler. |

## Ownership Lease

Session ownership is a sticky worker lease. It is separate from `AgentSession.run_state` and exists
to keep follow-up inputs on the same warm `_SessionRunner` and session-scoped toolkit lifecycle.

| Concept | Authority | Duration | Purpose |
| --- | --- | --- | --- |
| Sticky ownership lease | Redis session owner key | 30 minutes of session idle time | Route follow-up inputs to the same worker and preserve warm session toolkit lifecycle |
| Owner heartbeat | Redis owner heartbeat key | 120 seconds | Prove that the sticky owner worker is still alive |
| Heartbeat interval | Worker idle loop | 30 seconds | Refresh owner heartbeat while the runner is idle but still owns the session |
| Graceful release | Worker shutdown / runner teardown | Immediate | Return ownership when the worker intentionally stops owning the session |

The sticky lease and heartbeat timeout intentionally have different meanings:

- The 30-minute lease is the normal owner stickiness window.
- The 120-second heartbeat timeout is a failure detector. If the heartbeat is stale, another worker
  may revoke the owner even if the 30-minute sticky lease has not expired.
- A graceful shutdown must release both the owner lease and owner heartbeat immediately.

The Session activity projection carries the worker identity that wrote it. Readers fetch the
activity value, migration-authority marker, and sticky owner lock as one same-slot Lua snapshot.
An activity whose marker or embedded legacy owner differs from the current lock is stale and is
hidden or resolved through the compatible legacy projection. This prevents an ownership handoff
from combining an old activity value with a newer authority marker and presenting stale Run state.

## Worker State And Routing

`AgentSession.run_state` remains a coarse session execution recovery signal (`idle` / `running`).
Detailed execution state lives in `agent_runs.phase`, `active_tool_calls`, and nullable
`retry_state`. `AgentRuntime` owns shared sandbox lifecycle and runner/provider state, not session
run ownership.

Worker shutdown must not partially process a new message. If shutdown wins before processing, the
message is left for broker redelivery or ownership takeover.

If shutdown is observed while a foreground run is active, the run boundary is a worker handover
boundary, not an idle boundary. The current worker closes foreground tool and operation admission,
then allows already-admitted work up to 30 seconds to finish cleanly. Timeout cancels the supervised
task and lets its cancellation finalizers persist terminal state before the worker releases the
ownership lease and heartbeat. Even a clean return during shutdown must skip idle hooks, skip Goal
continuation creation, and skip `AgentSession.run_state=IDLE`. A new worker resumes from the durable
transcript, `agent_runs`, pending input buffers, and session wake-up state, while any leftover active
operation is cancelled rather than resumed.

Broker wake-up routing uses the ownership lease:

1. A producer commits model input or control state to Postgres, then publishes the complete broker
   envelope to `azents:incoming:v2` with one `XADD`. The Stream entry is both body and wake
   authority, so an ambiguous response means either the whole entry committed or nothing committed.
   The mutation is never retried.
2. During rolling deployment the producer also writes one uniquely identified compatibility copy
   to the legacy per-session LIST and global/direct wake Stream. Success of either independent path
   is sufficient. An ambiguous legacy append/expiry/publication gets one duplicate-safe repair wake.
3. Workers alternate v2 and legacy polling. A new worker that accepts a v2 entry removes that
   entry's exact compatibility LIST copy, preventing permanent dual-write backlog while still
   allowing old-only workers to run after a rollback.
4. A non-owner v2 worker assigns the pending entry to a live v2 owner's consumer with `XCLAIM` on
   the same global Stream. The owner reads its own PEL before reclaiming abandoned or new entries.
   When the owner is an old worker, the v2 entry remains authority until a LIST/direct-Stream bridge
   and its wake complete, then the relay ACKs v2.
5. A worker defers v2 `XACK` until its next receive call, after `AgentWorker` has handed the body to
   the in-memory SessionRunner. An ambiguous ACK can therefore produce a duplicate but cannot hide
   the only body before handoff.
6. If the sticky owner key exists but its heartbeat has been missing for 120 seconds, an observing
   worker may take over the lease and reclaim the pending v2 entry.

Redis Cluster imposes two routing constraints on the broker implementation:

- Complete-message publication is a single-key v2 `XADD`; it does not attempt a cross-slot Lua
  transaction between a session LIST, owner lease, and global/direct Stream.
- Owner lease scripts only touch keys that share the session hash tag, for example
  `azents:session:{session_id}:lock` and `azents:session:{session_id}:owner-heartbeat`.
- Legacy workers read the global incoming Stream and their worker direct Stream with separate
  `XREADGROUP` commands. They must not pass both stream keys to one Redis command because those
  streams can live in different cluster hash slots.
- Poison-envelope quarantine uses a one-key Lua append-plus-expiry mutation, so a response loss
  cannot leave an `invalid-messages` key without its retention TTL.

```mermaid
sequenceDiagram
    autonumber
    participant API as API / Producer
    participant R as Redis Broker
    participant WA as Worker A<br/>sticky owner
    participant WB as Worker B
    participant DB as Postgres

    WA->>R: acquire session lease<br/>(30m sticky + 120s heartbeat)
    WA->>DB: process run
    WA->>DB: mark run_state=IDLE
    Note over WA: Runner remains warm for sticky window
    loop every 30s while idle
        WA->>R: renew owner heartbeat<br/>(does not need a new user message)
    end

    API->>DB: commit input/control state
    API->>R: XADD complete envelope to v2 Stream
    API-->>R: legacy LIST + wake compatibility copy
    WB->>R: XREADGROUP v2 global Stream
    R->>R: owner heartbeat and v2 capability are live
    WB->>R: XCLAIM pending entry to WA
    WA->>R: read own pending entry
    WA->>R: remove exact legacy copy
    Note over WA,R: defer XACK until body is handed to SessionRunner
    WA->>DB: mark run_state=RUNNING
    WA->>DB: process follow-up input

    Note over WA: If WA stops gracefully
    WA->>R: release lease + heartbeat
    API->>R: next complete-message XADD
    WB->>R: acquire session lease and process
```

## Failure And Takeover

When a worker crashes, the sticky lease key can outlive the process. The owner heartbeat is the
failure detector:

```mermaid
sequenceDiagram
    autonumber
    participant WA as Worker A<br/>crashed owner
    participant API as API / Producer
    participant R as Redis Broker
    participant WB as Worker B
    participant DB as Postgres

    WA->>R: acquire session lease<br/>(30m sticky)
    WA->>R: renew heartbeat every 30s
    Note over WA: crash / OOM / node loss
    Note over R: heartbeat expires after 120s<br/>sticky lease key may still exist
    API->>DB: commit input/control state
    API->>R: XADD complete v2 envelope
    WB->>R: XAUTOCLAIM abandoned pending entry
    WB->>R: observe stale owner heartbeat
    WB->>R: steal session lease + heartbeat
    WB->>R: hand complete envelope to SessionRunner
    WB->>DB: mark run_state=RUNNING
    WB->>DB: resume from durable transcript / input buffers
```

The takeover path must preserve single-session execution:

- A live owner heartbeat prevents non-owner processing.
- A stale heartbeat permits lease stealing even if the 30-minute sticky key remains.
- Complete v2 entries remain pending in the consumer group until a worker with valid ownership
  hands them off. Legacy LIST bodies exist only for mixed-version compatibility. Model input
  payloads, operation action inputs, and control state remain durable in Postgres. Before an
  operation input buffer is deleted, its pending `ActionExecution`, typed action payload, and
  admitting `owner_generation` are committed under the source `input_buffer_id`. A takeover
  converts any surviving execution from an older processing boundary into a cancelled durable
  snapshot before consuming new input.
- Durable transcript and `agent_runs` remain the execution source of truth after takeover.

## Operation Action Recovery

Operation TurnActions enter through durable `action_message` InputBuffers, but they do not append an
`action_message` transcript event. Preparation claims a worktree action by committing an active
`ActionExecution` keyed by `input_buffer_id`, with its typed action payload and current Session owner
generation, then deletes the source buffer in the same transaction. The current worker verifies that
generation and crosses the foreground admission barrier before invoking a Runner side effect.

`action_executions` and their ordered events are live state only. Normal completion, handled failure,
user stop, shutdown timeout, and takeover recovery use one terminalization primitive: lock the active
row, build the terminal projection, append `action_execution_result:{execution_id}`, and delete the
live row and progress events in the same transaction. The worktree allocation survives through its
nullable `ON DELETE SET NULL` reference.

Takeover never resumes pending or running operation work. The side effect may have completed before
the previous worker lost its result, so the new owner conservatively snapshots the leftover operation
as cancelled and does not call its handler. Running workers process newly admitted TurnActions at
model-call turn boundaries instead of waiting for run completion. If a Project-mutating action
completes, the same active run rebuilds model/tool context before its next model call. A failed or
cancelled action is terminal, is not retried or discarded, and FIFO processing may continue to later
pending input.

## Failed-run Retry Recovery

When a running `agent_runs` row has non-null `retry_state`, that state is the durable retry resume
source. Recovery and handover must preserve the failed attempt count and `next_retry_at`; a worker
restart must not reset the retry budget or bypass exponential backoff. If a terminal transition closes
the run, terminal helpers clear `retry_state` so stale retry state cannot be resumed.

A worker that acquires a session during retry must treat the run as still active. It may re-enter the
same run boundary with the existing `run_id`; the adapter must reuse the existing `agent_runs` row
instead of creating a replacement row. Retry wait may be resumed from `next_retry_at`, and stop while
waiting finalizes the failed run with `finalization_reason = retry_stopped_by_user`. Shutdown while
waiting leaves the run `running` for the next worker instead of writing durable failed history.

## Inference Profile Recovery

Pending and running `AgentRun` rows are active recovery sources. Recovery claims the existing run and its ordered input-event associations rather than creating a new run boundary. The Session current inference snapshot is the turn execution authority: it contains requested label, resolved physical selection, effort, effective limits, and resolution time. Recovery must not overwrite it from older run-owned provenance. A pending normal input resolves during preparation; successful preparation atomically updates the Session snapshot with canonical events and buffer deletion. A handled resolution failure preserves the previous snapshot, appends a deterministic user-safe error, consumes the failed head, and completes the active run without retry. A later profile change within a running run updates the Session snapshot for the next turn and rebuilds that same run's request.

Manual failed-run retry is a distinct new pending run. It copies the original requested profile and ordered input associations, marks source `retry_original`, and leaves resolved provenance empty so current Agent routing is resolved once at activation. The first child subagent run is different: it is precreated with a parent run id and a complete resolved snapshot, effort, and limits. It uses source `parent_run` for exact inheritance or `spawn_override` for a statically resolved non-full-history override. Recovery activates either pre-resolved source without re-routing the requested label, so first-run execution does not depend on whether the original target label still exists. Later child runs resolve the stored session-last-used label normally.

## Tool Recovery

Tool recovery reconciles the durable call event, active ownership entry, terminal result, and owner generation before any resumed model dispatch. A previous-generation active call is cancelled best effort and receives one deterministic `client_tool_result(status=cancelled)`. A durable call without active ownership or result is an orphan and receives the same cancelled result without handler execution. A result with stale active ownership keeps the existing result and removes only the stale ownership entry. Completed tool results are never re-executed, and duplicate recovery converges through the result external ID.

## User Stop Resume Boundary

User-requested stop is a terminal interruption, not a sticky stop condition for future turns. The
stop finalizer consumes the durable stop request, records user stop events, and clears
`AgentSession.stop_requested_at` before the next wake-up can process buffered input. The durable
event order for a stopped run is:

1. Any live assistant/reasoning projection that can be persisted.
2. Missing foreground tool results repaired as cancelled/interrupted tool results.
3. `interrupted` with `reason=user_requested`.
4. `run_marker(status=interrupted)`.

If an operation TurnAction is active, the same preemptive task cancellation first converts it into a
cancelled durable snapshot and removes its live row; the handler is not left for replay. If an input
buffer is already pending when stop handling finishes, the warm session runner must enqueue or
preserve a wake-up so the next run starts immediately. A stale stop request must not cause that next
run to observe `check_stop()` as true.

## Invariants

- Durable transcript, ordered run-input associations, and pending/running `agent_runs` are the resume source of truth.
- The Session inference snapshot is complete and atomic per turn; recovery never restores it from an older AgentRun snapshot.
- `agent_runs.retry_state` is the resume source for failed-run retry progress while a run remains running.
- A live sticky owner must receive a v2 pending entry by same-Stream consumer assignment, or a
  legacy direct wake during mixed-version rollout.
- A non-owner worker must not process a session while the owner heartbeat is live.
- A stale owner heartbeat revokes the sticky owner even if the 30-minute lease key has not expired.
- In-memory worker state is not required after crash because takeover resumes from durable state.
- Shutdown/handover run completion is not quiescent idle and must not dispatch idle continuation
  hooks.
- Completed tool results are not duplicated.
- User stop intent is consumed by stop finalization and must not interrupt the next wake-up.
- A leftover nonterminal operation is cancelled into one durable snapshot before new work; operation handlers are never resumed or replayed after ownership loss.
- SDK `RunState` compatibility is not preserved.


## Changelog

- **2026-07-14** (spec_version 21) — Made Session activity, migration marker, and owner-lock reads one same-slot authority snapshot across worker handoff.
- **2026-07-14** (spec_version 20) — Made complete-message v2 Stream entries the atomic broker authority, added mixed-version dual delivery and legacy bridging, same-Stream owner assignment, deferred ACK, fair protocol polling, and atomic poison quarantine TTLs.
- **2026-07-14** (spec_version 19) — Replaced operation resume with owner-generation-fenced live execution, atomic terminal snapshot/delete handover, 30-second graceful shutdown, and cancelled no-reexecution takeover recovery.
- **2026-07-12** (spec_version 18) — Made ownership generation and durable call/result state authoritative for no-reexecution tool recovery.
- **2026-07-12** (spec_version 17) — Promoted Session-owned per-turn inference recovery, handled preparation failure, buffer-only action transport, buffer-keyed action recovery, and same-run context rebuild.
- **2026-07-11** (spec_version 16) — Added recovery semantics for pre-resolved `spawn_override` child runs and later session-last-used re-resolution.
- **2026-07-10** (spec_version 15) — Added pending/activated profile recovery, retry intent re-resolution, and exact inherited parent-run snapshot recovery.
- **2026-07-08** (spec_version 14) — Clarified that failed TurnActions continue FIFO processing and context invalidation uses a cancelled run boundary plus follow-up wake-up, not a completed run marker.
- **2026-07-08** (spec_version 13) — Clarified that running workers process TurnActions at model-call turn boundaries and hand off after context invalidation.
- **2026-07-06** (spec_version 12) — Removed session-initialization recovery and documented durable terminal action result recovery.
- **2026-07-05** (spec_version 11) — Added operation TurnAction recovery semantics for action-based Git worktree setup.
