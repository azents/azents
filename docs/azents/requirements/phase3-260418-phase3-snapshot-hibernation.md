---
title: "Phase 3 — Agent Home Snapshot Hibernation Discussion Historical Requirements Reconstruction"
created: 2026-04-18
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: phase3-260418
historical_reconstruction: true
migration_source: "docs/azents/adr/0021-phase3-snapshot-hibernation.md"
---

# Phase 3 — Agent Home Snapshot Hibernation Discussion Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `phase3-260418`
- Source: `docs/azents/adr/phase3-260418-phase3-snapshot-hibernation.md`
- Historical source date basis: `2026-04-18`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Phase 1 (#2609) completed DB-based activity tracking and lifecycle hooks. Phase 2 (#2627) completed the deadline-driven lifecycle loop and lease token. Phase 3 replaces the current "idle for 30 minutes → delete" behavior with **"idle → hibernate → resume."**

When an agent becomes idle during long-running work such as code analysis, builds, or tests, this phase preserves the **ephemeral layer** state—installed packages, shell history, filesystem changes, and similar state—as a snapshot, then restores it within a few seconds when the user returns.

Prerequisites: #2608 (research), #2609 (Phase 1), #2627 (Phase 2), #2661 (Phase 3 discussion), Discussion #2664.

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
