---
title: "Keep Action Messages Buffer-Only Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: action-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0131-keep-action-messages-buffer-only.md"
---

# Keep Action Messages Buffer-Only Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `action-260712`
- Source: `docs/azents/adr/action-260712-action-messages-buffer-only.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

`action_message` is an input-buffer envelope that carries a typed TurnAction, optional user-authored text, and inference overrides into preparation. Earlier designs and the current implementation also promote that envelope into a durable `action_message` transcript event before appending action-specific events.

The sequential preparation model does not need that intermediate durable representation. Once the action has been interpreted, durable history should contain the semantic preparation results and the model-visible user message rather than the queue envelope that transported them.

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
