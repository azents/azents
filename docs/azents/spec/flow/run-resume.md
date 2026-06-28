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
  - python/apps/azents/src/azents/repos/agent_run/**
  - python/apps/azents/src/azents/repos/agent_runtime/**
  - python/apps/azents/src/azents/engine/run/contracts.py
  - python/apps/azents/src/azents/engine/events/**
  - python/apps/azents/src/azents/engine/run/types.py
  - python/apps/azents/src/azents/worker/session/**
last_verified_at: 2026-06-28
spec_version: 8
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
| Active event run | `agent_runs.phase`, `active_tool_calls`, and `retry_state` | Runtime reconciles phase/tool/retry state and repairs missing interrupted results |
| Pending tool call | Event transcript has call without result | Runtime executes or interrupts the missing result path without duplicating completed results |

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

## Worker State And Routing

`AgentSession.run_state` remains a coarse session execution recovery signal (`idle` / `running`).
Detailed execution state lives in `agent_runs.phase`, `active_tool_calls`, and nullable
`retry_state`. `AgentRuntime` owns shared sandbox lifecycle and runner/provider state, not session
run ownership.

Worker shutdown must not partially process a new message. If shutdown wins before processing, the
message is left for broker redelivery or ownership takeover.

If shutdown is observed while a foreground run is active, the run boundary is a worker handover
boundary, not an idle boundary. The current worker may wait briefly for `engine.run()` to finish
cleanly, but even a clean return during shutdown must skip idle hooks, skip Goal continuation
creation, and skip `AgentSession.run_state=IDLE`. The worker releases the ownership lease and heartbeat; a new
worker resumes from the durable transcript, `agent_runs`, pending input buffers, and session
wake-up state.

Broker wake-up routing uses the ownership lease:

1. A producer commits model input or control state to Postgres, then stores a wake-up signal in the
   per-session wake-up list.
2. If the session has a live owner heartbeat, the producer publishes the wake-up to the owner
   worker's direct stream.
3. If there is no live owner heartbeat, the producer publishes to the global incoming stream.
4. A non-owner worker that observes a global wake-up for a live owner does not process the message.
   It forwards the wake-up to the owner worker's direct stream.
5. If the sticky owner key exists but the owner heartbeat has been missing for 120 seconds, the
   observing worker may take over the session lease and process queued wake-ups.

Redis Cluster imposes two routing constraints on the broker implementation:

- Owner lease scripts only touch keys that share the session hash tag, for example
  `azents:session:{session_id}:lock` and `azents:session:{session_id}:owner-heartbeat`.
- Workers read the global incoming stream and their worker direct stream with separate
  `XREADGROUP` commands. They must not pass both stream keys to one Redis command because those
  streams can live in different cluster hash slots.

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
    API->>R: RPUSH session wake-up
    R->>R: owner heartbeat is live
    R->>WA: XADD owner direct stream
    WA->>R: XREADGROUP owner direct stream
    WA->>R: drain session wake-up list
    WA->>DB: mark run_state=RUNNING
    WA->>DB: process follow-up input

    Note over WA: If WA stops gracefully
    WA->>R: release lease + heartbeat
    API->>R: next message
    R->>R: no live owner
    R->>WB: XADD global incoming
    WB->>R: acquire session lease
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
    API->>R: RPUSH session wake-up signal
    R->>R: sticky owner exists, heartbeat missing
    R->>WB: XADD global incoming
    WB->>R: observe stale owner heartbeat
    WB->>R: steal session lease + heartbeat
    WB->>R: drain session wake-up list
    WB->>DB: mark run_state=RUNNING
    WB->>DB: resume from durable transcript / input buffers
```

The takeover path must preserve single-session execution:

- A live owner heartbeat prevents non-owner processing.
- A stale heartbeat permits lease stealing even if the 30-minute sticky key remains.
- Wake-up signals remain in the per-session Redis list until a worker with valid ownership drains
  them. Model input payloads and control state remain durable in Postgres.
- Durable transcript and `agent_runs` remain the execution source of truth after takeover.

## Failed-run Retry Recovery

When a running `agent_runs` row has non-null `retry_state`, that state is the durable retry resume
source. Recovery and handover must preserve the failed attempt count and `next_retry_at`; a worker
restart must not reset the retry budget or bypass exponential backoff. If a terminal transition closes
the run, terminal helpers clear `retry_state` so stale retry state cannot be resumed.

## Tool Recovery

If a foreground tool call has no corresponding result after interruption, the runtime appends a
synthetic `client_tool_result(status=interrupted)` and then appends a terminal run marker. Completed
tool results are never re-executed.

## User Stop Resume Boundary

User-requested stop is a terminal interruption, not a sticky stop condition for future turns. The
stop finalizer consumes the durable stop request, records user stop events, and clears
`AgentSession.stop_requested_at` before the next wake-up can process buffered input. The durable
event order for a stopped run is:

1. Any live assistant/reasoning projection that can be persisted.
2. Missing foreground tool results repaired as cancelled/interrupted tool results.
3. `interrupted` with `reason=user_requested`.
4. `run_marker(status=interrupted)`.

If an input buffer is already pending when stop handling finishes, the warm session runner must
enqueue or preserve a wake-up so the next run starts immediately. A stale stop request must not cause
that next run to observe `check_stop()` as true.

## Invariants

- Durable transcript and `agent_runs` are the resume source of truth.
- `agent_runs.retry_state` is the resume source for failed-run retry progress while a run remains running.
- A live sticky owner must receive follow-up broker wake-ups directly.
- A non-owner worker must not process a session while the owner heartbeat is live.
- A stale owner heartbeat revokes the sticky owner even if the 30-minute lease key has not expired.
- In-memory worker state is not required after crash because takeover resumes from durable state.
- Shutdown/handover run completion is not quiescent idle and must not dispatch idle continuation
  hooks.
- Completed tool results are not duplicated.
- User stop intent is consumed by stop finalization and must not interrupt the next wake-up.
- SDK `RunState` compatibility is not preserved.
