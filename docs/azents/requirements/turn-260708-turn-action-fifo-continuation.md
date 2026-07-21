---
title: "Continue FIFO Processing After Failed TurnActions Historical Requirements Reconstruction"
created: 2026-07-08
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: turn-260708
historical_reconstruction: true
migration_source: "docs/azents/adr/0097-turn-action-fifo-continuation.md"
---

# Continue FIFO Processing After Failed TurnActions Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `turn-260708`
- Source: `docs/azents/adr/turn-260708-turn-action-fifo-continuation.md`
- Historical source date basis: `2026-07-08`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[action-260705/ADR](../adr/action-260705-action-as-operation-turn-actions.md) modeled session operations as ordered TurnActions. Its original failure policy stopped later
pending input until the user retried or discarded the failed operation action. During the prerequisite
stack validation, this behavior conflicted with the intended turn-boundary queue semantics: a failed
TurnAction is a terminal result for that action, not a permanent run/session blocker.

The same validation found that successful Project-mutating TurnActions must still be a context
invalidation boundary. Continuing with a stale model/tool context after `session_workspace_projects`
changes can omit the new Project, Project-scoped instructions, and Skill projection from the next
model call.

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
