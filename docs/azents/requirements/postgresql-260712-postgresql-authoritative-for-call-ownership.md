---
title: "Make PostgreSQL Authoritative for Tool Call Ownership Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: postgresql-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0143-make-postgresql-authoritative-for-tool-call-ownership.md"
---

# Make PostgreSQL Authoritative for Tool Call Ownership Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `postgresql-260712`
- Source: `docs/azents/adr/postgresql-260712-postgresql-authoritative-for-call-ownership.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Foreground client tool execution crosses model output persistence, handler side effects, worker shutdown, ownership takeover, result persistence, and live UI delivery. Redis activity and live-event projections previously duplicated active-call state, so recovery could observe a call event, active marker, and result from different authorities. Retrying an unresolved call after worker loss could duplicate a non-idempotent side effect.

Azents requires deterministic recovery without assuming that arbitrary tool handlers are idempotent.

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
