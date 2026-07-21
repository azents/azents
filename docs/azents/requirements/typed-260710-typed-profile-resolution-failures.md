---
title: "Expose Typed Actionable Profile Resolution Failures Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: typed-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0120-typed-profile-resolution-failures.md"
---

# Expose Typed Actionable Profile Resolution Failures Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `typed-260710`
- Source: `docs/azents/adr/typed-260710-typed-profile-resolution-failures.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Strict run-time target resolution intentionally does not fall back when a requested label disappears, routing cannot choose an eligible model, or an explicit effort becomes unsupported. A generic system-error string cannot reliably drive user recovery, message provenance details, or operational grouping. Rejecting only at enqueue time is insufficient because configuration can change while an input waits in FIFO order.

The UI must remain actionable without exposing credentials, decrypted configuration, or unnecessary internal provider diagnostics.

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
