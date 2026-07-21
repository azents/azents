---
title: "Remove Deprecated Background Completion Input Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: background-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0134-remove-background-completion-input.md"
---

# Remove Deprecated Background Completion Input Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `background-260712`
- Source: `docs/azents/adr/background-260712-background-completion-input.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents still contains a background-task completion pipeline that can inject `background_completion` input buffers into a parent session. The dedicated Background feature is deprecated and has no active product use, but its registry, toolkit, runtime-coordination publication, worker queue, event kind, input-buffer kind, tests, and specifications remain in the codebase.

Keeping an unused asynchronous input source complicates the sequential input-buffer redesign and preserves recovery and idempotency machinery for behavior the product no longer exposes.

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
