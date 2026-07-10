---
title: "ADR-0116: Store Requested Inference Profiles as Typed Durable Data"
created: 2026-07-10
tags: [architecture, backend, database, events]
---

# ADR-0116: Store Requested Inference Profiles as Typed Durable Data

## Context

A requested target and effort control FIFO segmentation while an input is pending and provide historical provenance after it is promoted into the transcript. The existing InputBuffer metadata is a string map intended for general message metadata. Encoding execution policy there would weaken validation, require parsing during run segmentation, and risk leaking policy fields into model-facing message metadata.

InputBuffer rows are deleted after promotion, so requested intent also needs an immutable transcript representation. Physical model resolution must remain absent until AgentRun start under ADR-0105.

## Decision

Add first-class nullable typed fields to InputBuffer persistence and domain models:

- `requested_model_target_label` as a nullable string;
- `requested_reasoning_effort` as a nullable PostgreSQL enum value.

The valid states are:

- non-null target plus non-null effort: explicit target and effort;
- non-null target plus null effort: explicit target with visible `Default` no-override effort;
- null target plus null effort: internal or implicit input that inherits run/session context;
- null target plus non-null effort: invalid and rejected by a database constraint and service validation.

Run-producing public user inputs always populate a non-null target under ADR-0115. Null target remains available for internal execution paths that intentionally inherit session/run context.

When an InputBuffer becomes an immutable `user_message` event, copy its intent into a typed nullable `requested_inference_profile` payload object containing `model_target_label` and nullable `reasoning_effort`. Existing transcript events and internal user-message events without explicit prompt intent decode with a null profile.

Do not store provider IDs, physical model IDs, model-selection snapshots, context limits, or routing results in InputBuffer or user-message requested-profile fields. AgentRun provenance owns resolved execution data.

## Rejected options

### Store profile fields in general message metadata

Execution policy would be stringly typed, mixed with model-facing metadata, and harder to validate and compare.

### Store one JSONB profile column

The shape mirrors the API but weakens database typing and constraints for fields used directly by FIFO segmentation.

### Store the requested profile only on AgentRun

Queued messages need profile-aware segmentation and visible target metadata before an AgentRun exists.

### Resolve and store a physical model on InputBuffer

This violates run-time routing and makes queued prompts insensitive to current target policy.

## Consequences

- A database migration adds two InputBuffer columns, an effort enum, and a consistency constraint.
- InputBuffer repository and service contracts gain typed requested-profile fields.
- FIFO prefix selection can compare target and effort without parsing metadata.
- `UserMessagePayload` gains a nullable structured requested-profile field.
- Pending live events and durable history can project the same requested target label and effort.
- InputBuffer deletion does not erase requested intent because promotion copies it to the immutable event.
