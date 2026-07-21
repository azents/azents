---
title: "Goal Continuation Uses Idle Hook and Input Buffer Historical Requirements Reconstruction"
created: 2026-06-15
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: goal-260615
historical_reconstruction: true
migration_source: "docs/azents/adr/0062-goal-continuation-idle-hook.md"
---

# Goal Continuation Uses Idle Hook and Input Buffer Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `goal-260615`
- Source: `docs/azents/adr/goal-260615-goal-continuation-idle-hook.md`
- Historical source date basis: `2026-06-15`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[goal-260613/ADR](../adr/goal-260613-goal-pursuing.md) decided that Goal is owned at `AgentSession` scope. [input-260615/ADR](../adr/input-260615-input-control-plane-clean-migration.md) organized source of truth for model-visible payload entering session runner into `input_buffers` and reduced broker to control plane responsible only for wake-up and stop signal.

Goal pursuing must start automatic continuation turn when a session with active Goal becomes idle. This behavior is better provided as a generalized lifecycle where runtime hook providers can request continuation input at idle time, rather than only as Goal-specific worker service.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Add `InputBufferKind.GOAL_CONTINUATION` with DB value `goal_continuation`.

Goal continuation is not a message directly written by user, but it is model-visible payload entering session runner, so it is stored in `input_buffers`.

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
