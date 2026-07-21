---
title: "Persist Inference Provenance on Turn Usage Markers Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: persist-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0142-persist-turn-usage-inference-provenance.md"
---

# Persist Inference Provenance on Turn Usage Markers Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `persist-260712`
- Source: `docs/azents/adr/persist-260712-persist-turn-usage-inference-provenance.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

A durable `turn_marker` stores provider-reported token usage and the producing `run_id`. The chat token indicator can currently show model/profile context only while a matching live Run projection is available. After terminal cleanup, reload, or live-state parse failure, the durable usage remains but its model target, reasoning effort, model display, and effective limits become unavailable.

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-73) keeps resolved inference provenance owned by AgentRun and rejects mutating or republishing user-message history events as Run state changes. That decision correctly protects append-only transcript ordering, but it leaves immutable per-turn usage facts without the inference snapshot needed to interpret them later.

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
