---
title: "Handle Message Edits as Transactional Preparation Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: handle-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0127-handle-message-edits-as-transactional-preparation.md"
---

# Handle Message Edits as Transactional Preparation Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `handle-260712`
- Source: `docs/azents/adr/handle-260712-handle-message-edits-as-transactional-preparation.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current edit path rewrites durable history and then creates an `edited_user_message` input buffer. The worker later promotes that buffer into a replacement `user_message` event. This splits one edit operation across the REST transaction and the input-buffer preparation loop, exposes the replacement as pending UI state, and adds a buffer kind whose behavior is not normal FIFO input preparation.

[drain-260712/ADR](../adr/drain-260712-drain-input-buffers-before-turn-start.md) makes input-buffer processing a sequential preparation stage before turn start. An edit already requires an idle-only lock, durable history rewrite, and immediate history reload, so routing its replacement message through the buffer adds an unnecessary intermediate state.

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
