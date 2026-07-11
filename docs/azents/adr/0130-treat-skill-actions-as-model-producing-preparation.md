---
title: "ADR-0130: Treat Skill Actions as Model-Producing Preparation"
created: 2026-07-12
tags: [architecture, agent, backend, engine, skill]
---

# ADR-0130: Treat Skill Actions as Model-Producing Preparation

## Context

A `skill` TurnAction selects an exact Skill projection and may include a user-authored instruction plus model and effort overrides. Loading the Skill is preparation for model execution rather than a state-only control operation. Without a following turn, the selected Skill body and user instruction would be stored but never acted upon.

ADR-0125 drains input buffers before turn start, ADR-0126 resolves message inference settings during preparation, and ADR-0129 defines handled preparation failures as consumed and non-turn-producing.

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

A handled Skill resolution or validation failure follows ADR-0129: append a durable failure result, do not change session inference settings, consume the buffer, continue draining, and do not start a turn when that failure remains the final preparation outcome.

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

- [ADR-0086: Introduce Typed Chat Action Messages](./0086-chat-action-messages.md)
- [ADR-0087: Use Revisioned Filesystem Skill Projections](./0087-filesystem-skill-projection-revisions.md)
- [ADR-0125: Drain Input Buffers Sequentially Before Turn Start](./0125-drain-input-buffers-before-turn-start.md)
- [ADR-0126: Resolve User Message Profiles During Buffer Preparation](./0126-resolve-user-message-profile-during-buffer-preparation.md)
- [ADR-0129: Consume Failed Buffer Items Without Starting a Turn](./0129-consume-failed-buffer-items-without-starting-a-turn.md)
