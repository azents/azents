---
title: "Treat Skill Actions as Model-Producing Preparation"
created: 2026-07-12
tags: [architecture, agent, backend, engine, skill, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: skill-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0130-treat-skill-actions-as-model-producing-preparation.md"
---

# skill-260712/ADR: Treat Skill Actions as Model-Producing Preparation

## Context

A `skill` TurnAction selects an exact Skill projection and may include a user-authored instruction plus model and effort overrides. Loading the Skill is preparation for model execution rather than a state-only control operation. Without a following turn, the selected Skill body and user instruction would be stored but never acted upon.

[drain-260712/ADR](./drain-260712-drain-input-buffers-before-turn-start.md) drains input buffers before turn start, [message-260712/ADR](./message-260712-message-profile-during-buffer-preparation.md) resolves message inference settings during preparation, and [consume-260712/ADR](./consume-260712-consume-failed-buffer-items-without-starting-a-turn.md) defines handled preparation failures as consumed and non-turn-producing.

## Decision

Treat `action_message.skill` as a model-producing input-buffer item.

For a successful SkillAction preparation:

1. Resolve the exact `skill_path` from the active Skill projection.
2. Snapshot the selected Skill body and required projection metadata for durable model input.
3. Resolve the action's effective model and effort configuration.
4. Append the durable SkillAction and loaded-Skill preparation events.
5. Update the AgentSession's current resolved inference configuration.
6. Delete the processed input-buffer row.

The durable events, session inference update, and buffer deletion form one atomic preparation result. Processing then continues with later FIFO buffers. When the buffer becomes empty, a successfully prepared SkillAction establishes turn eligibility and the next turn uses the final resolved session inference configuration.

A handled Skill resolution or validation failure follows [consume-260712/ADR](./consume-260712-consume-failed-buffer-items-without-starting-a-turn.md): append a durable failure result, do not change session inference settings, consume the buffer, continue draining, and do not start a turn when that failure remains the final preparation outcome.

The exact durable event shape for preserving the optional user-authored message without duplication is a follow-up feature-design decision.

## Rejected Alternative

### Treat SkillAction as state-only control

Loading a Skill without starting a model turn cannot execute the selected workflow and makes the action's model and effort overrides ineffective.

## Consequences

- SkillAction participates in next-turn eligibility like GoalAction and normal user input.
- Skill lookup and body snapshotting occur before turn creation.
- SessionRunner consumes prepared Skill events and the final session inference configuration; it does not resolve Skill selection from the original buffer.
- Skill resolution failures are durable and non-blocking under the shared failure baseline.
- The design must define one canonical location for the optional user-authored instruction to avoid duplicate model-visible messages.

## References

- [chat-260630/ADR: Introduce Typed Chat Action Messages](./chat-260630-chat-action-messages.md)
- [filesystem-260701/ADR: Use Revisioned Filesystem Skill Projections](./filesystem-260701-filesystem-skill-projection-revisions.md)
- [drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start](./drain-260712-drain-input-buffers-before-turn-start.md)
- [message-260712/ADR: Resolve User Message Profiles During Buffer Preparation](./message-260712-message-profile-during-buffer-preparation.md)
- [consume-260712/ADR: Consume Failed Buffer Items Without Starting a Turn](./consume-260712-consume-failed-buffer-items-without-starting-a-turn.md)

## Migration provenance

- Historical source filename: `0130-treat-skill-actions-as-model-producing-preparation.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
