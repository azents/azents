---
title: "Treat Goal Actions as Model-Producing Preparation Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: goal-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0128-treat-goal-actions-as-model-producing-preparation.md"
---

# Treat Goal Actions as Model-Producing Preparation Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `goal-260712`
- Source: `docs/azents/adr/goal-260712-goal-actions-as-producing-preparation.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

A `goal` TurnAction carries a user-authored objective plus model and effort overrides. Its preparation mutates session Goal state, but the user's intent is also an instruction that should be handled by the next model turn. Treating it as state-only control would update Goal without allowing the agent to begin acting on or responding to that objective.

[drain-260712/ADR](../adr/drain-260712-drain-input-buffers-before-turn-start.md) requires input buffers to be processed one at a time before turn start, and [message-260712/ADR](../adr/message-260712-message-profile-during-buffer-preparation.md) moves message inference configuration resolution into buffer preparation.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

This updates session Goal state without giving the model a turn to acknowledge or begin acting on the new objective. It also makes the model and effort overrides carried by the action meaningless.

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
