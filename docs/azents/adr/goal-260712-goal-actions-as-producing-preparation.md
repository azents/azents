---
title: "Treat Goal Actions as Model-Producing Preparation"
created: 2026-07-12
tags: [architecture, agent, backend, engine, goal, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: goal-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0128-treat-goal-actions-as-model-producing-preparation.md"
---

# goal-260712/ADR: Treat Goal Actions as Model-Producing Preparation

## Context

A `goal` TurnAction carries a user-authored objective plus model and effort overrides. Its preparation mutates session Goal state, but the user's intent is also an instruction that should be handled by the next model turn. Treating it as state-only control would update Goal without allowing the agent to begin acting on or responding to that objective.

[drain-260712/ADR](./drain-260712-drain-input-buffers-before-turn-start.md) requires input buffers to be processed one at a time before turn start, and [message-260712/ADR](./message-260712-message-profile-during-buffer-preparation.md) moves message inference configuration resolution into buffer preparation.

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

- [goal-260615/ADR: Goal Continuation Uses Idle Hook and Input Buffer](./goal-260615-goal-continuation-idle-hook.md)
- [chat-260630/ADR: Introduce Typed Chat Action Messages](./chat-260630-chat-action-messages.md)
- [drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start](./drain-260712-drain-input-buffers-before-turn-start.md)
- [message-260712/ADR: Resolve User Message Profiles During Buffer Preparation](./message-260712-message-profile-during-buffer-preparation.md)

## Migration provenance

- Historical source filename: `0128-treat-goal-actions-as-model-producing-preparation.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
