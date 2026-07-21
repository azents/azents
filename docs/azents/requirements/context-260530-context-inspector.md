---
title: "Session Context Inspector Historical Requirements Reconstruction"
created: 2026-05-30
implemented: 2026-05-30
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: context-260530
historical_reconstruction: true
migration_source: "docs/azents/adr/0041-session-context-inspector.md"
---

# Session Context Inspector Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `context-260530`
- Source: `docs/azents/adr/context-260530-context-inspector.md`
- Historical source date basis: `2026-05-30`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents stores agent execution as canonical events and already records per-turn model usage in `turn_marker` events. The chat UI currently exposes token usage only inline at turn boundaries. This makes it hard to diagnose context bloat, oversized tool outputs, unexpected compaction pressure, or projection bugs because there is no single place to inspect the current session context and the raw canonical events behind the rendered chat.

OpenCode exposes a session context view with usage stats, approximate token breakdown, system prompt visibility, and raw message inspection. Azents needs an equivalent inspector that fits its canonical transcript architecture.

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
