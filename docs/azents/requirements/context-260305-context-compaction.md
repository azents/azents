---
title: "Agent Context Compaction Historical Requirements Reconstruction"
created: 2026-03-05
implemented: 2026-03-23
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: context-260305
historical_reconstruction: true
migration_source: "docs/azents/design/context-compaction.md"
---

# Agent Context Compaction Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `context-260305`
- Source: `docs/azents/design/context-260305-context-compaction.md`
- Historical source date basis: `2026-03-05`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

**threshold = `effective_max_input_tokens * 0.9`** (hardcoded, configurable later)

`effective_max_input_tokens` is calculated as `min(main_model_max_input, summary_model_max_input)`. If summary model has smaller context window than main model, threshold must be based on summary model so summary model can read history while generating compaction summary.

`max_input_tokens` 3-step fallback:

```python

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

[What goal(s) is the user trying to accomplish?]

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
