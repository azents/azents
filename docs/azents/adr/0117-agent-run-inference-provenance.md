---
title: "ADR-0117: Persist Requested and Resolved AgentRun Provenance"
created: 2026-07-10
tags: [architecture, backend, database, observability, routing]
---

# ADR-0117: Persist Requested and Resolved AgentRun Provenance

## Context

A per-prompt target is durable intent, while the provider/model selected at run start is execution fact. Agent target configuration and future routing policy can change after execution, so reconstructing historical resolution from current Agent state is not reliable. Resolution failures also need an AgentRun record even though no physical model snapshot exists.

One AgentRun can consume multiple FIFO user messages. A user message can later participate in another AgentRun through manual retry, while automatic retries remain attempts inside the same run. A single foreign key on either side cannot represent these relationships accurately.

## Decision

Persist typed requested provenance on every model-producing AgentRun:

- `requested_model_target_label`;
- nullable `requested_reasoning_effort`;
- `inference_profile_source` enum.

Profile-source values initially distinguish:

- `explicit_input`;
- `session_last_used`;
- `agent_default`;
- `parent_run`;
- `retry_original`.

Materialize the selected requested label and effort onto the AgentRun even when the source was implicit. A new model-producing run does not retain null requested target after session/default precedence has selected one.

Persist resolved provenance after successful authoritative routing:

- immutable `resolved_model_selection` JSONB using the internal `AgentModelSelection` snapshot;
- nullable effective `resolved_reasoning_effort`;
- `resolved_at` timestamp;
- effective context-window tokens;
- effective auto-compaction threshold tokens.

The internal snapshot may include the provider integration ID and normalized catalog diagnostics needed for audit, but never credentials or decrypted provider configuration. Public projections expose only safe provider/model/capability fields.

Create the AgentRun row with requested provenance before target resolution. On success, atomically add resolved provenance before model execution. On resolution failure, keep resolved fields null and mark the run failed, preserving requested provenance.

Represent message/run participation with an `agent_run_input_events` association table containing:

- `agent_run_id`;
- `event_id`;
- `input_order`.

This supports several user messages in one run and the same original message in later manual-retry runs. Automatic retry does not create another AgentRun or association. The message provenance UI defaults to the latest associated run and can expose prior attempts in expanded details.

## Rejected options

### Store one opaque provenance JSON object

Typed source, target, and effort fields are important for query, validation, and operational inspection. Only the naturally nested resolved model snapshot remains JSONB.

### Reconstruct resolution from transcript and current Agent configuration

Current routing state may differ from the execution-time snapshot, and failed resolution has no physical model to reconstruct.

### Put a single run foreign key on user messages

Manual retry makes the relation one message to multiple runs, while FIFO grouping makes it multiple messages to one run.

### Create the AgentRun only after successful resolution

Resolution failures would have no durable run identity or requested provenance.

## Consequences

- AgentRun creation moves before authoritative target resolution and records the selected intent source.
- A database migration adds requested/resolved provenance columns, source enum, and the input-event association table.
- Run-start resolution must persist the snapshot and effective limits before invoking the model.
- Context/token usage can use run-scoped limits under ADR-0114.
- User-message hover/touch details can join requested message intent to actual resolution and retry history under ADR-0112.
- Historical AgentRun rows predating this feature may have null provenance fields. Database nullability/constraints must permit those rows, while service-level creation and activation enforce complete requested provenance for every new model-producing run.
