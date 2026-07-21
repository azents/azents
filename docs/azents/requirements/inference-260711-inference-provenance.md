---
title: "Keep Resolved Inference Provenance Run-Owned Historical Requirements Reconstruction"
created: 2026-07-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: inference-260711
historical_reconstruction: true
migration_source: "docs/azents/adr/0124-keep-inference-provenance-run-owned.md"
---

# Keep Resolved Inference Provenance Run-Owned Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `inference-260711`
- Source: `docs/azents/adr/inference-260711-inference-provenance.md`
- Historical source date basis: `2026-07-11`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[inline-260710/ADR](../adr/inline-260710-inline-message-inference-summary.md) projected the latest associated AgentRun summary into durable chat events and required the worker to republish existing `history_event_appended` events whenever run provenance changed. The frontend replaced the existing timeline item with the republished event.

This made an append-only transcript transport behave like a mutable projection. A user input could be broadcast repeatedly as its run was created, resolved, retried, or completed. Replacing the old item by removing and appending it moved historical inputs to the bottom of the timeline, while accepting every broadcast created duplicates. The event-level projection also required history and live REST reads to join events back to AgentRuns.

Resolved model display for historical messages is useful, but it does not justify mutating or reordering canonical transcript events.

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
