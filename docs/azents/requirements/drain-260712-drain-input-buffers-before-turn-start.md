---
title: "Drain Input Buffers Sequentially Before Turn Start Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: drain-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0125-drain-input-buffers-before-turn-start.md"
---

# Drain Input Buffers Sequentially Before Turn Start Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `drain-260712`
- Source: `docs/azents/adr/drain-260712-drain-input-buffers-before-turn-start.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current input-buffer path treats pending inputs as chunks that may be promoted together according to action and requested-profile boundaries. It may also inject matching pending input at a later model-call boundary inside an active run. This makes buffer draining, run selection, and turn execution part of one combined operation.

That coupling complicates ordering and message-type semantics. Different buffer kinds need different preparation effects, but chunk promotion requires deciding their shared run behavior before each item has been handled independently.

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
