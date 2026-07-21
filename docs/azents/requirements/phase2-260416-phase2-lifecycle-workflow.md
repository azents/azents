---
title: "Phase 2 — Durable Lifecycle Workflow + Lease Token Discussion Historical Requirements Reconstruction"
created: 2026-04-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: phase2-260416
historical_reconstruction: true
migration_source: "docs/azents/adr/0020-phase2-durable-lifecycle-workflow.md"
---

# Phase 2 — Durable Lifecycle Workflow + Lease Token Discussion Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `phase2-260416`
- Source: `docs/azents/adr/phase2-260416-phase2-lifecycle-workflow.md`
- Historical source date basis: `2026-04-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Phase 1 (#2609) established DB-based activity tracking and lifecycle hooks. Phase 2 replaces the current simple 60-second poll+delete loop with a **deadline-driven lifecycle loop + DB lease token** to improve correctness, failure recovery, and scalability.

Prerequisites: #2608 (research), #2609 (Phase 1)
Vercel reference: `apps/web/lib/sandbox/lifecycle.ts`, `lifecycle-kick.ts`

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
