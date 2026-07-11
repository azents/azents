---
title: "ADR-0126: Resolve User Message Profiles During Buffer Preparation"
created: 2026-07-12
tags: [architecture, agent, backend, engine, frontend, session]
---

# ADR-0126: Resolve User Message Profiles During Buffer Preparation

## Context

ADR-0105 resolves a requested model target when an AgentRun starts, and ADR-0121 updates the AgentSession last-used profile as part of run activation. Under ADR-0125, input-buffer draining is now a preparation stage that completes before the next turn starts. Keeping label resolution in SessionRunner run preparation would preserve an unnecessary coupling between queued message semantics and turn creation.

A user message carries the user-authored content, including attachments and file parts, plus optional model and reasoning-effort overrides. Processing that message must apply those settings deterministically while preserving an immutable account of what the message changed.

## Decision

Process each `user_message` input buffer as one inference-configuration transition and one durable message append.

For a successful user-message preparation:

1. Combine the message's model and effort overrides with the current session inference configuration.
2. Resolve the effective model target label to an eligible model selection and resolve the effective effort.
3. Append one immutable durable `user_message` event containing the message and the inference configuration applied by that message.
4. Update the AgentSession's current resolved model selection and effort to the same applied configuration.
5. Delete the processed input-buffer row.

The durable event append, session inference-configuration update, and buffer deletion form one atomic preparation result. Resolution happens before that atomic write so the event is complete when first appended and is never backfilled or reordered later.

A later input buffer may apply another inference configuration. After the entire input buffer is empty, the next turn uses the final resolved session inference configuration. SessionRunner consumes that already-resolved configuration and no longer owns model-target-label-to-model-selection resolution for normal buffered execution.

The model information stored on a user-message event means **the resolved configuration applied to the session by that message**. It does not mean that a model invocation was performed for that individual message. When several messages are drained before one turn, an earlier message may record one applied configuration while a later message replaces it and the turn uses the final configuration.

Actual execution provenance remains internal AgentRun state. It is not a required user-message event field and does not need to be exposed in the chat UI. The UI may display the immutable applied message configuration without joining or mutating the event from later AgentRun state.

Field names must express these semantics. Existing names such as `requested_inference_profile`, `last_model_target_label`, or inference-run summary names may be replaced where they imply request-only intent, last-run usage, or actual execution provenance. The feature design will define the concrete replacement schema and migration.

This decision supersedes ADR-0105 for normal buffered user-message resolution and supersedes ADR-0121 where it delays the corresponding session profile update until AgentRun activation. ADR-0124 continues to apply to actual execution provenance: AgentRun remains its owner, while the event stores only the configuration applied during message preparation.

## Rejected Alternatives

### Resolve the message only when the next AgentRun starts

This keeps the current worker boundary but prevents buffer preparation from completing the message's state transition. It also requires later event enrichment or a separate inference from run state if the UI needs to show what configuration the message applied.

### Append requested intent first and mutate the event after resolution

This creates a historical event mutation path and makes event ordering and projections depend on later run lifecycle state.

### Expose actual AgentRun provenance on each user-message event

Several buffered messages can contribute to one turn, so a per-message execution attribution is not a stable ownership model. It would also require historical joins or mutation after the turn starts.

## Consequences

- User-message events are complete and immutable at initial append.
- Session inference configuration becomes the prepared input to turn creation rather than an output of run activation.
- Multiple queued user messages apply configuration transitions in FIFO order; the last applied configuration wins for the next turn.
- SessionRunner and run creation no longer resolve model target labels for normal buffered user messages.
- AgentRun still stores internal execution provenance for retry, recovery, and operations, but chat UI exposure is not required.
- Resolution-failure behavior and the concrete event/session field schema remain follow-up feature-design decisions.

## References

- [ADR-0105: Resolve Prompt Model Targets at Run Time](./0105-run-time-model-target-resolution.md)
- [ADR-0121: Atomically Activate the Resolved Run and Session Profile](./0121-atomic-run-profile-activation.md)
- [ADR-0124: Keep Inference Provenance Run-Owned](./0124-keep-inference-provenance-run-owned.md)
- [ADR-0125: Drain Input Buffers Sequentially Before Turn Start](./0125-drain-input-buffers-before-turn-start.md)
