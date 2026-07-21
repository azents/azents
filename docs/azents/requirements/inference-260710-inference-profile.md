---
title: "Store Requested Inference Profiles as Typed Durable Data Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: inference-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0116-durable-requested-inference-profile-storage.md"
---

# Store Requested Inference Profiles as Typed Durable Data Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `inference-260710`
- Source: `docs/azents/adr/inference-260710-inference-profile.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

A requested target and effort control FIFO segmentation while an input is pending and provide historical provenance after it is promoted into the transcript. The existing InputBuffer metadata is a string map intended for general message metadata. Encoding execution policy there would weaken validation, require parsing during run segmentation, and risk leaking policy fields into model-facing message metadata.

InputBuffer rows are deleted after promotion, so requested intent also needs an immutable transcript representation. Physical model resolution must remain absent until AgentRun start under [time-260710/ADR](../adr/time-260710-time-target-resolution.md).

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
