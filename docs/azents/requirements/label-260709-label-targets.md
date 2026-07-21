---
title: "Label-Based Model Targets Historical Requirements Reconstruction"
created: 2026-07-09
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: label-260709
historical_reconstruction: true
migration_source: "docs/azents/adr/0100-label-based-model-targets.md"
---

# Label-Based Model Targets Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `label-260709`
- Source: `docs/azents/adr/label-260709-label-targets.md`
- Historical source date basis: `2026-07-09`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents previously stored Agent main and lightweight models as direct `AgentModelSelection` snapshots. That kept runtime simple, but it did not provide a durable abstraction for a curated set of models that can be reused by Agent settings, future per-run chat selection, future subagent model selection, and future dynamic model routing.

Provider model identifiers are not a good UI or policy boundary for those future features. Exposing raw provider models everywhere would make chat and delegation surfaces depend on full provider catalogs and would require repeated catalog resolution at run start.

Azents also needs to preserve snapshot-based runtime behavior. Runtime should use saved, resolved model snapshots and should not query model catalogs, provider listing APIs, or Workspace defaults during run start.

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
