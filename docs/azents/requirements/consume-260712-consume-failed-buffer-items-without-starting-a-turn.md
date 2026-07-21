---
title: "Consume Failed Buffer Items Without Starting a Turn Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: consume-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0129-consume-failed-buffer-items-without-starting-a-turn.md"
---

# Consume Failed Buffer Items Without Starting a Turn Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `consume-260712`
- Source: `docs/azents/adr/consume-260712-consume-failed-buffer-items-without-starting-a-turn.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[drain-260712/ADR](../adr/drain-260712-drain-input-buffers-before-turn-start.md) drains input buffers sequentially before deciding whether to start the next turn. Individual preparation items can fail for expected reasons, such as an invalid Goal transition or an inference-profile resolution failure. Leaving such an item pending would block all later FIFO work, while starting a model turn for a failed item would spend a model call even though no valid model-producing preparation was completed.

The same rule must apply consistently across buffer kinds so each type does not invent its own queue-blocking or turn-start behavior.

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
