---
title: "ADR-0128: Treat Goal Actions as Model-Producing Preparation"
created: 2026-07-12
tags: [architecture, agent, backend, engine, goal]
---

# ADR-0128: Treat Goal Actions as Model-Producing Preparation

## Context

A `goal` TurnAction carries a user-authored objective plus model and effort overrides. Its preparation mutates session Goal state, but the user's intent is also an instruction that should be handled by the next model turn. Treating it as state-only control would update Goal without allowing the agent to begin acting on or responding to that objective.

ADR-0125 requires input buffers to be processed one at a time before turn start, and ADR-0126 moves message inference configuration resolution into buffer preparation.

## Decision

Treat `action_message.goal` as a model-producing input-buffer item.

For a successful GoalAction preparation:

1. Validate the requested Goal objective and current Goal state.
2. Resolve the action's effective model and effort configuration.
3. Append an immutable durable `action_message` event containing the GoalAction, user-authored objective, and applied resolved inference configuration.
4. Create the active session Goal state.
5. Append the corresponding durable `goal_updated` event.
6. Update the AgentSession's current resolved inference configuration.
7. Delete the processed input-buffer row.

The action event, Goal state transition, Goal update event, session inference update, and buffer deletion form one atomic preparation result.

Processing then continues with the next pending buffer. After the buffer is empty, the prepared GoalAction contributes actionable model input and causes the next turn to start using the final resolved session inference configuration.

The GoalAction does not start a turn immediately when later buffers remain. Later model-producing inputs and inference-configuration transitions are prepared first according to FIFO order.

Failure representation, whether failed GoalAction intent remains model-actionable, and whether a failed action applies its requested inference configuration remain follow-up feature-design decisions.

## Rejected Alternative

### Treat GoalAction as state-only control

This updates session Goal state without giving the model a turn to acknowledge or begin acting on the new objective. It also makes the model and effort overrides carried by the action meaningless.

## Consequences

- GoalAction participates in next-turn eligibility like a normal user message.
- Goal state mutation remains a typed preparation side effect rather than being inferred by the model.
- GoalAction applies model and effort settings to the session on successful preparation.
- Multiple pending inputs are still fully drained before one next turn starts.
- GoalAction success must be transactionally consistent across transcript, Goal state, session inference configuration, and input-buffer deletion.

## References

- [ADR-0062: Goal Continuation Uses Idle Hook and Input Buffer](./0062-goal-continuation-idle-hook.md)
- [ADR-0086: Introduce Typed Chat Action Messages](./0086-chat-action-messages.md)
- [ADR-0125: Drain Input Buffers Sequentially Before Turn Start](./0125-drain-input-buffers-before-turn-start.md)
- [ADR-0126: Resolve User Message Profiles During Buffer Preparation](./0126-resolve-user-message-profile-during-buffer-preparation.md)
