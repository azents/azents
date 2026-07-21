---
title: "Use Polymorphic Input Buffer Processors Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: polymorphic-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0136-use-polymorphic-input-buffer-processors.md"
---

# Use Polymorphic Input Buffer Processors Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `polymorphic-260712`
- Source: `docs/azents/adr/polymorphic-260712-polymorphic-input-buffer-processors.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current `InputBufferService` combines FIFO selection, profile-segment construction, buffer-kind branching, action-subtype branching, domain side effects, event construction, run association, deletion, and turn-boundary behavior in one service. The new design processes exactly one FIFO item at a time, and each remaining buffer kind now has an explicit preparation contract.

Those contracts differ enough to require separate implementations but share one queue lifecycle and one structured turn-effect model. Keeping a single growing conditional would make the sequential redesign easier to implement initially but harder to test and extend safely.

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
