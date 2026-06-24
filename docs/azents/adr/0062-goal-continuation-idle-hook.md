---
title: "ADR-0062: Goal Continuation Uses Idle Hook and Input Buffer"
created: 2026-06-15
tags: [architecture, backend, engine, api, chat]
---

# ADR-0062: Goal Continuation Uses Idle Hook and Input Buffer

## Context

ADR-0060 decided that Goal is owned at `AgentSession` scope. ADR-0061 organized source of truth for model-visible payload entering session runner into `input_buffers` and reduced broker to control plane responsible only for wake-up and stop signal.

Goal pursuing must start automatic continuation turn when a session with active Goal becomes idle. This behavior is better provided as a generalized lifecycle where runtime hook providers can request continuation input at idle time, rather than only as Goal-specific worker service.

## Decision

### ADR-0062-D1. Add Goal continuation input buffer kind

Add `InputBufferKind.GOAL_CONTINUATION` with DB value `goal_continuation`.

Goal continuation is not a message directly written by user, but it is model-visible payload entering session runner, so it is stored in `input_buffers`.

### ADR-0062-D2. Goal continuation promotes to separate durable event kind

Add `EventKind.GOAL_CONTINUATION`.

A `goal_continuation` buffer promotes to `goal_continuation` event in durable transcript, distinguished from user messages. UI may render this event differently from user bubble or hide it.

### ADR-0062-D3. LLM lower role uses existing user role

Goal continuation does not define a new role in LLM API. Like Azents system reminder, durable event taxonomy and LLM lower role are separated.

Therefore, `goal_continuation` event uses existing user role when lowered to model input.

### ADR-0062-D4. Add idle continuation lifecycle hook

Add `on_session_idle` lifecycle to runtime hook system.

`on_session_idle` is called when a session run ends and the session reviews idle continuation. This hook is a continuation decision hook, not an observation hook.

### ADR-0062-D5. `on_session_idle` returns zero or more continuation inputs

`on_session_idle` callback returns `SessionIdleResult | None`. `None` is same as empty result.

`SessionIdleResult` has `continuations: list[SessionContinuationInput]`. Minimum fields of `SessionContinuationInput` are:

- `content: str`
- `metadata: dict[str, str]`

If multiple hook providers return continuations, dispatcher merges all of them in provider order. It does not arbitrate by selecting only the first request.

### ADR-0062-D6. Worker/runtime stores hook result into input buffer and wakes up

Hook provider returns only continuation input. It does not directly perform DB write or broker wake-up.

Worker/runtime stores merged continuation input as `InputBufferKind.GOAL_CONTINUATION` rows, transitions session to running wake-up state, then sends `SessionWakeUp`.

Dispatcher or worker/runtime adds provider slug to metadata.

### ADR-0062-D7. GoalToolkit is the first `on_session_idle` provider

GoalToolkit checks session-scoped active Goal. If Goal status is `active`, it returns Codex-style continuation prompt as `SessionContinuationInput`.

If Goal status is `paused`, `blocked`, `complete`, or Goal is absent, it returns no continuation.

Budget, token accounting, and `budget_limited` state are out of scope for this decision and handled in follow-up phase.

## Consequences

### Positive

- Goal continuation is provided through general idle lifecycle rather than Goal-specific worker path.
- Multiple providers can request continuation input, and all use the same input buffer control plane.
- Broker keeps only wake-up/signal role from ADR-0061.
- Goal continuation is distinguished from user messages in durable transcript and UI taxonomy.
- No new LLM lower role is created, avoiding provider API constraints.

### Negative / Trade-offs

- `InputBufferKind`, `EventKind`, and promotion/rendering taxonomy need expansion.
- `on_session_idle` differs from existing observation hooks as decision hook, increasing dispatcher contract.
- Separate decision is needed for how UI displays `goal_continuation` event.

## Alternatives

### Add Goal-specific continuation service directly to worker

Rejected. It fits Goal quickly but does not support future continuation providers well.

### Let hook provider directly manipulate input buffer and broker

Rejected. Toolkit/provider would know runtime control plane directly, blurring idle atomicity and failure isolation.

### Store continuation in a separate buffer

Rejected. After ADR-0061, input buffer is source of truth for session runner payload, so continuation should use the same buffer taxonomy.

### Do not persist continuation as durable event

Rejected. Auto continuation should be traceable for operations/audit, and a separate event kind distinct from user message is clearer.

## Related Documents

- [ADR-0060: Goal pursuing uses session-scoped ownership](./0060-session-scoped-goal-pursuing.md)
- [ADR-0061: Separate input payload and control action with DB source of truth](./0061-input-control-plane-clean-migration.md)
