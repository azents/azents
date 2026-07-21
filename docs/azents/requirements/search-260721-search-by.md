---
title: "Enable Tool Search by Default for New Agents Historical Requirements Reconstruction"
created: 2026-07-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: search-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0178-enable-tool-search-by-default.md"
---

# Enable Tool Search by Default for New Agents Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `search-260721`
- Source: `docs/azents/adr/search-260721-search-by.md`
- Historical source date basis: `2026-07-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-195) introduced Tool Search as an Agent-level opt-in capability with a default-disabled setting. The initial default prioritized compatibility while Azents validated deferred capability discovery, provider declaration budgets, prepared-call execution boundaries, and product-path behavior.

Those validations are complete. Models reliably recognize the direct Tool Search capability, discover deferred tools when needed, and show acceptable tool-selection performance. Keeping Tool Search disabled by default now preserves a larger legacy tool catalog without a corresponding product benefit.

The `agents.tool_search_enabled` column is a non-null persisted setting. Existing `false` values may represent deliberate administrator opt-outs, but the historical schema does not distinguish those from values created by the former default.

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
