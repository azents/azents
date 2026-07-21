---
title: "Subagent Human Write Boundary Historical Requirements Reconstruction"
created: 2026-07-09
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: subagent-260709
historical_reconstruction: true
migration_source: "docs/azents/adr/0098-subagent-human-write-boundary.md"
---

# Subagent Human Write Boundary Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `subagent-260709`
- Source: `docs/azents/adr/subagent-260709-subagent-human-write-boundary.md`
- Historical source date basis: `2026-07-09`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents adopted a Codex-first subagent model where subagents are child `AgentSession` actors coordinated by the parent agent through model-visible collaboration tools. The frontend exposes child session detail views so users can inspect child transcripts and navigate the subagent tree.

A child detail view is an observation surface, not a human chat target. If a user can bypass the UI and directly mutate a child session through REST writes, the product model becomes ambiguous: work could enter a subagent outside the parent orchestration path, child Todo/Goal state could be edited independently by a human, and future mailbox/follow-up semantics would have to account for unmanaged human-origin inputs.

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
