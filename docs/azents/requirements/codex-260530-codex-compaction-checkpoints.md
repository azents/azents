---
title: "Generate Compaction Summary as Codex-like Handoff Checkpoint Historical Requirements Reconstruction"
created: 2026-05-30
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: codex-260530
historical_reconstruction: true
migration_source: "docs/azents/adr/0043-codex-like-compaction-checkpoints.md"
---

# Generate Compaction Summary as Codex-like Handoff Checkpoint Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `codex-260530`
- Source: `docs/azents/adr/codex-260530-codex-compaction-checkpoints.md`
- Historical source date basis: `2026-05-30`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents canonical runtime replaces old model input with `compaction_summary` in long-running sessions. After [compaction-260530/ADR](../adr/compaction-260530-compaction-logical-event-ordering.md), auto compaction preserves tail as raw events, and summary replaces only the compacted range.

Next, summary quality and size control become important. Existing prompt is closer to a conversation summary, and in OpenAI/ChatGPT OAuth Responses calls, `max_output_tokens` is omitted due to streaming path. In this state, summary can become too long, or branch/PR/file/test/error/current-state information needed for the next agent to continue may not be preserved structurally.

The user wants a Codex-like strategy. The core idea is to treat compaction summary not as a user-visible answer or conversation narrative, but as a durable handoff checkpoint that lets the next agent/model step continue work without rereading the compacted transcript.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
