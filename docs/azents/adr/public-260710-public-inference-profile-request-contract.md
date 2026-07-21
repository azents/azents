---
title: "Use an Explicit Nested Inference Profile Request"
created: 2026-07-10
tags: [architecture, api, chat, routing, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: public-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0115-public-inference-profile-request-contract.md"
---

# public-260710/ADR: Use an Explicit Nested Inference Profile Request

## Context

Per-prompt selection requires every run-producing human input to carry durable target intent before it enters the FIFO buffer. Deriving a queued message's target later from mutable AgentSession state would make its requested profile ambiguous. Allowing clients to submit provider or physical model snapshots would bypass the Agent-owned target policy introduced by [label-260709/ADR](./label-260709-label-targets.md).

The chat API has separate request shapes for a new session's first message, existing-session Composer input, message editing, failed-run retry, and commands. Model target and reasoning effort form one conceptual inference profile and may gain additional target-policy attributes in the future.

## Decision

Define a shared nested public request object named `inference_profile` containing:

- required `model_target_label`;
- required nullable `reasoning_effort`, where `null` represents the visible `Default` selection under [selection-260710/ADR](./selection-260710-reasoning-effort-selection.md).

Do not accept provider IDs, provider model IDs, credentials, context limits, resolved model snapshots, or routing results from clients.

Require a non-null `inference_profile` for every human input that can create an AgentRun:

- a new session's first message;
- a normal existing-session message;
- a turn-producing action such as Goal or Skill;
- an edited user message.

The failed-run retry request does not accept an inference profile override. It reuses the original requested target and effort under [reexecution-260710/ADR](./reexecution-260710-reexecution-target-intent.md).

A Composer command that does not invoke the main model uses `inference_profile: null`. Because the current `ChatInputWriteRequest` represents both commands and turn-producing input, its field is required but nullable. The API rejects a null profile for a run-producing input and rejects a non-null profile for a non-model command.

The server persists the submitted target label and effort as intent but does not resolve them to a physical model during request acceptance. Authoritative resolution remains at AgentRun start under [time-260710/ADR](./time-260710-time-target-resolution.md).

## Rejected options

### Add flat target and effort fields to every request

This repeats one conceptual object across request contracts and makes future profile evolution harder to keep consistent.

### Let run-producing user inputs omit the profile

Deriving it later from mutable session state weakens the per-prompt FIFO boundary and prevents a queued message from exposing a definitive requested label.

### Accept resolved model snapshots from clients

This bypasses Agent routing policy and trusts stale or unauthorized provider configuration.

### Allow retry-time profile override

Manual retry preserves the original target intent. Changing it is a separate edit/new-input operation and future override functionality is outside this contract.

## Consequences

- Public OpenAPI schemas and generated clients gain a shared inference-profile request type.
- Existing human message clients must send the current Composer profile explicitly.
- Request validation is action-aware for the required nullable field on the combined Composer input endpoint.
- User-message and InputBuffer state can always identify the requested profile before run start.
- Future dynamic routing can evolve behind `model_target_label` without changing clients or exposing physical model configuration.

## Migration provenance

- Historical source filename: `0115-public-inference-profile-request-contract.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
