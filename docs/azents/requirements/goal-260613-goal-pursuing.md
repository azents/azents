---
title: "Goal Pursuing Is Owned at Session Scope Historical Requirements Reconstruction"
created: 2026-06-13
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: goal-260613
historical_reconstruction: true
migration_source: "docs/azents/adr/0060-session-scoped-goal-pursuing.md"
---

# Goal Pursuing Is Owned at Session Scope Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `goal-260613`
- Source: `docs/azents/adr/goal-260613-goal-pursuing.md`
- Historical source date basis: `2026-06-13`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

To introduce Codex-style goal pursuing into Azents within a realistic scope, Goal ownership scope must be fixed first. Codex manages a single persisted goal per thread, and if an active goal remains, it is used as basis for idle continuation.

Azents has both parent agent sessions and subagent sessions. If Goal is inherited or shared from parent to subagent, automatic continuation, complete judgment, blocked judgment, and user control get mixed across session boundaries. Conversely, if Goal is run-scoped, pursuing state that persists across turns cannot be represented.

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
