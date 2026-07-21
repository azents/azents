---
title: "Per-Prompt Reasoning Effort Is a Run Boundary Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: boundaries-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0104-per-prompt-reasoning-effort-run-boundaries.md"
---

# Per-Prompt Reasoning Effort Is a Run Boundary Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `boundaries-260710`
- Source: `docs/azents/adr/boundaries-260710-prompt-reasoning-effort-boundaries.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[prompt-260710/ADR](../adr/prompt-260710-prompt-fifo-boundaries.md) defines a prompt's selected main model as a FIFO `AgentRun` boundary and preserves the invariant that one run uses one main model. Reasoning-capable models may also expose a finite set of configurable effort levels. Users need to choose an effort together with the model for each prompt.

`RunRequest.reasoning_effort` is currently fixed for the lifetime of an `AgentRun`. Applying a newly queued effort inside the active run would make the effective inference profile vary between model calls even when the main model is unchanged. That would create the same retry, audit, and observability ambiguity that [prompt-260710/ADR](../adr/prompt-260710-prompt-fifo-boundaries.md) avoids for model changes.

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
