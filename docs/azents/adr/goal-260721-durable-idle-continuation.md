---
title: "Durable Goal Idle Continuation"
created: 2026-07-21
tags: [goal, backend, worker, architecture]
document_role: primary
document_type: adr
snapshot_id: goal-260721
---

# goal-260721/ADR: Durable Goal Idle Continuation

## Context

[goal-260721/REQ](../requirements/goal-260721-durable-idle-continuation.md) requires an active Goal to retain its automatic continuation when a completed run races Worker shutdown or process recovery. The current session runner retains the completed terminal boundary only in memory until it reaches true idle, so Worker teardown can discard it.

## Decisions

### goal-260721/ADR-D1. Store one durable pending idle-boundary pointer on `AgentSession`

For [goal-260721/REQ-1](../requirements/goal-260721-durable-idle-continuation.md#req-1-durable-completed-run-continuation-obligation) and [goal-260721/REQ-2](../requirements/goal-260721-durable-idle-continuation.md#req-2-ordered-continuation-after-true-idle), `AgentSession` stores a nullable reference to the one completed `AgentRun` whose session-idle continuation remains pending.

The pointer is written atomically with a `completed` terminal Run transition. It is not written for other terminal statuses. Starting an actionable replacement run clears the prior pointer because the session did not remain idle at that earlier boundary.

A per-run boundary table was rejected because it would turn the existing single, supersedable idle boundary into a backlog and could emit multiple continuations after one idle drain.

### goal-260721/ADR-D2. Consume the pointer only through an atomic idle-boundary outcome

For [goal-260721/REQ-2](../requirements/goal-260721-durable-idle-continuation.md#req-2-ordered-continuation-after-true-idle), [goal-260721/REQ-3](../requirements/goal-260721-durable-idle-continuation.md#req-3-exactly-once-logical-continuation), and [goal-260721/REQ-4](../requirements/goal-260721-durable-idle-continuation.md#req-4-existing-terminal-state-policy), the runner dispatches `on_session_idle` only after local and durable pending work is drained.

The final transaction conditionally consumes the matching pointer and commits one outcome:

- continuation InputBuffers plus `running` state; or
- no continuation plus `idle` state.

Continuation buffers use deterministic keys derived from the boundary run, hook provider, and provider-local continuation ordinal. The conditional pointer consume is the primary fence; idempotent InputBuffer insertion protects retry after a partial failure. The pointer is never cleared before its outcome commits.

Enqueuing continuation at terminalization was rejected because it would run before true idle, could overtake pending user/system work, and could use stale Goal state.

### goal-260721/ADR-D3. Handover and recovery treat a pending pointer as recoverable work

For [goal-260721/REQ-1](../requirements/goal-260721-durable-idle-continuation.md#req-1-durable-completed-run-continuation-obligation), graceful release sends a handover wake-up when either an active Run or a pending idle-boundary pointer remains. Stuck-session recovery retains the `running` state until the pointer is consumed and can therefore resume it through the existing wake-up path.

A new owner re-resolves current session hook providers rather than serializing Toolkit objects. Idle hooks are retryable decision hooks; current session state is authoritative when the session actually reaches idle.

## Consequences

- Completed-run continuation intent survives Worker memory loss without creating a historical queue of continuations.
- Pending user/system work retains precedence over automatic Goal continuation.
- InputBuffers remain the durable payload authority and broker messages remain signals.
- The terminal Run transition, replacement-run activation, handover, recovery, and idle consumption paths must all preserve the pointer invariant.
- Re-resolving hooks after handover may observe newer toolkit configuration, which is appropriate because evaluation is deferred to the actual idle boundary.
