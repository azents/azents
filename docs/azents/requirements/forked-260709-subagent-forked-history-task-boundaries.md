---
title: "Mark Forked History Boundaries for Subagent Tasks Historical Requirements Reconstruction"
created: 2026-07-09
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: forked-260709
historical_reconstruction: true
migration_source: "docs/azents/adr/0101-subagent-forked-history-task-boundaries.md"
---

# Mark Forked History Boundaries for Subagent Tasks Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `forked-260709`
- Source: `docs/azents/adr/forked-260709-subagent-forked-history-task-boundaries.md`
- Historical source date basis: `2026-07-09`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents subagents can receive forked parent history through `fork_turns`. When the fork includes all or part of the parent conversation, earlier user instructions remain visible to the subagent. Without an explicit boundary, the subagent can misread those inherited user instructions as direct instructions for its own current task.

Codex-compatible subagent behavior relies on two separate signals:

1. a boundary between inherited parent history and the subagent's current assignment; and
2. an explicit envelope for the parent-to-subagent task payload.

Azents should preserve these signals instead of relying on role ordering alone.

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
