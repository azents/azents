---
title: "Require an Explicit Reasoning Effort in User Input Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: effort-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0123-require-explicit-reasoning-effort-in-user-input.md"
---

# Require an Explicit Reasoning Effort in User Input Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `effort-260710`
- Source: `docs/azents/adr/effort-260710-reasoning-effort-in-input.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[selection-260710/ADR](../adr/selection-260710-reasoning-effort-selection.md) exposed the provider-default `null` value as a visible `Default` choice in the prompt composer. That representation preserves the runtime distinction between an explicit effort and no provider override, but it makes user intent ambiguous: a reasoning-capable model can be submitted without the user seeing which effort will be used.

LiteLLM publishes sparse reasoning capability flags rather than one ordered effort array. Azents must reconstruct the selectable list consistently, and an empty reconstructed list cannot safely be interpreted as unrestricted support.

Agent settings also need a deterministic initial effort coupled to the Agent's default model. Workspace settings only seed model choices for new Agents and do not need a separate reasoning-effort default.

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
