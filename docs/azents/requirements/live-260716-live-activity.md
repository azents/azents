---
title: "Normalize Provider Tool Live Activity Across Model Adapters Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: live-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0163-normalize-provider-tool-live-activity.md"
---

# Normalize Provider Tool Live Activity Across Model Adapters Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `live-260716`
- Source: `docs/azents/adr/live-260716-live-activity.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Provider-hosted tools execute inside a model-provider stream rather than through the Azents client-tool executor. Some provider transports emit lifecycle observations while a hosted tool is running, but Azents currently creates canonical provider-tool events only after the complete model response has been normalized. Long-running hosted tools such as Web search therefore look like model latency even when the provider has already reported active work.

Provider transports expose different native event classes, identities, and status vocabularies. Making the engine, live-state store, API, or frontend depend on one provider's stream events would violate the adapter boundary and require repeated product changes for each future native adapter.

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
