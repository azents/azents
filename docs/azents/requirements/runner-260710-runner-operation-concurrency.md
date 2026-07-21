---
title: "Session-Scoped Runner Operation Concurrency Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: runner-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0102-session-scoped-runner-operation-concurrency.md"
---

# Session-Scoped Runner Operation Concurrency Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `runner-260710`
- Source: `docs/azents/adr/runner-260710-runner-operation-concurrency.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

A Runtime Runner is shared by multiple Agent Sessions. The current Runner applies one `max_concurrent_operations` value to all operations in the Runtime, so concurrent Sessions contend for the same four execution slots. This makes the configured value behave as a Runtime-wide limit even though it was intended to bound each Session independently. Long-running process operations can therefore delay short file operations and Session initialization work from unrelated Sessions.

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
