---
title: "Usage-based Auto Compaction and Token Estimation Redesign"
created: 2026-06-12
updated: 2026-06-12
tags: [backend, engine, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: auto-260612
migration_source: "docs/azents/design/usage-based-auto-compaction.md"
historical_reconstruction: true
---

# Usage-based Auto Compaction and Token Estimation Redesign

## Background

Existing canonical pre-lower pipeline stringified the entire canonical event payload right before model call, estimated token count with `chars / 4`, and replaced old tool output with placeholders if estimate exceeded input budget. This method includes storage/debug metadata, JSON keys, and native structures much more than actual model-visible input, so it can incorrectly judge context pressure even when actual provider usage is low.

## Goals

- Remove behavior that automatically omits old tool output from normal model input.
- Base auto compaction decision on provider token usage from latest turn marker.
- Add token estimate only for events added after latest turn marker that are not yet reflected in provider usage.
- Compute token estimate from model-visible byte cost, not entire canonical payload.

## Design

### Remove tool output omit

Remove the filter that replaces old tool output with placeholders due to context pressure in normal pre-lower path. Tool output preserves original meaning in canonical history and model input. If large output management is needed, handle it with separate per-output truncation policy.

### Auto compaction decision

Auto compaction filter calculates baseline token count by adding:

1. `usage.prompt_tokens` from latest `turn_marker`
2. model-visible token estimate of events after that turn marker

If no latest turn marker exists, use model-visible token estimate of the entire transcript. If baseline token count is at or above `compute_auto_compaction_threshold_tokens(max_input_tokens)`, run append-only compaction. When automatic compaction creates a checkpoint, store `reason: auto_threshold_exceeded` in `compaction_marker` and `compaction_summary` payloads. Explicit `/compact` stores `reason: manual_command` at the same location.

### Token estimation

Event token estimate first calculates model-visible byte cost, then converts with `ceil(bytes / 4)`.

- Exclude storage metadata, event id, timestamp, schema version, and native artifact.
- Count only values visible to model input, such as user/assistant text, reasoning text/summary, tool call name/arguments, and tool result text.
- For attachment/file/image parts, count only placeholder text or compact representation of part metadata that enters the model, not raw object size.
- Structured payload uses compact JSON serialization instead of Python `str(dict)`.

This estimate does not replace provider usage; it applies only to local delta after provider usage or initial history without provider usage.

## Test Strategy

- Unit test `CanonicalAutoCompactionFilter` verifies that no compaction occurs when latest turn marker usage is below threshold, even if old large tool output exists.
- Verify compaction occurs by summing provider usage and delta estimate when a large event is added after latest turn marker.
- Verify full transcript estimate fallback works when there is no turn marker.
- Remove tests related to tool output context-pressure placeholder, and verify by assembly test that the filter is absent from pre-lower pipeline.
