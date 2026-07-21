---
title: "Expose Default as a Reasoning Effort Selection Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: selection-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0111-reasoning-effort-default-selection.md"
---

# Expose Default as a Reasoning Effort Selection Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `selection-260710`
- Source: `docs/azents/adr/selection-260710-reasoning-effort-selection.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Reasoning-capable model targets can advertise different selectable effort levels. A user may switch the Composer from a model that supports the current explicit effort to one that does not. Preserving an unsupported value until run start creates an avoidable failure, while requiring another selection after every incompatible model change adds friction.

The runtime already represents the absence of an explicit reasoning-effort override as `null`. This is a meaningful requested-profile value: the resolved model or provider applies its default behavior rather than Azents selecting another effort level.

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
