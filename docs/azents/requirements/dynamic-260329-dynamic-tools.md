---
title: "Dynamic Tool Management — Toolkit State Machine Historical Requirements Reconstruction"
created: 2026-03-29
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: dynamic-260329
historical_reconstruction: true
migration_source: "docs/azents/adr/0013-dynamic-tools.md"
---

# Dynamic Tool Management — Toolkit State Machine Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `dynamic-260329`
- Source: `docs/azents/adr/dynamic-260329-dynamic-tools.md`
- Historical source date basis: `2026-03-29`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

At run start, the engine synchronously waits for `create_tools()` from every toolkit, builds the system prompt, then starts the LLM call. The tool list and system prompt are fixed at run start and cannot change afterward.

1. **First response blocking**: one slow MCP server delays the start of the entire run, even when the user asks a question unrelated to MCP.
2. **Sandbox dependency**: stdio MCP sidecar Pod must be ready before list_tools can run. The engine becomes dependent on sandbox lifecycle.
3. **No dynamic changes**: tool additions/removals during a run are not reflected, such as after OAuth completion or MCP `list_changed`.

All three problems come from one constraint: **the tool list is fixed at run start**.

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
