---
title: "Remove Percentage Rollout from Apply-Patch Custom Selection Historical Requirements Reconstruction"
created: 2026-07-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: custom-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0180-remove-apply-patch-custom-rollout.md"
---

# Remove Percentage Rollout from Apply-Patch Custom Selection Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `custom-260721`
- Source: `docs/azents/adr/custom-260721-patch-custom-rollout.md`
- Historical source date basis: `2026-07-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[patch-260721/ADR](../adr/patch-260721-patch-dialects.md) introduced a provider-specific plaintext-custom transport for the logical
`apply_patch` tool. Its initial implementation added a percentage-based cohort selector
and adapter configuration to control exposure. That selector is a feature flag and is
not part of the required provider-dialect behavior.

The supported transport boundary is already an exact code-owned conjunction of provider,
authentication mode, adapter, endpoint class, model identifier, and semantic profile.
Adding a session- or tenant-derived percentage decision makes identical supported routes
present different client-tool contracts for reasons unrelated to provider compatibility.

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
