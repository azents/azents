---
title: "Subagents Inherit the Parent Run Profile Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: subagent-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0108-subagent-parent-run-profile-inheritance.md"
---

# Subagents Inherit the Parent Run Profile Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `subagent-260710`
- Source: `docs/azents/adr/subagent-260710-subagent-parent-profile-inheritance.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Subagents execute through internal subagent AgentSessions and the same worker/AgentRun path as the root session. A newly spawned subagent has no prior session inference profile. Applying the Agent default or re-resolving only the parent's target could make the child start with a different physical model than the parent run that delegated the task.

Subagents are children of a concrete running parent `AgentRun`, so their initial execution profile should be part of the forked execution context. Future explicit subagent model overrides are planned but are outside the scope of the per-prompt model-selection feature.

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
