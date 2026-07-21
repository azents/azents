---
title: "Treat Skill Actions as Model-Producing Preparation Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: skill-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0130-treat-skill-actions-as-model-producing-preparation.md"
---

# Treat Skill Actions as Model-Producing Preparation Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `skill-260712`
- Source: `docs/azents/adr/skill-260712-skill-actions-as-producing-preparation.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

A `skill` TurnAction selects an exact Skill projection and may include a user-authored instruction plus model and effort overrides. Loading the Skill is preparation for model execution rather than a state-only control operation. Without a following turn, the selected Skill body and user instruction would be stored but never acted upon.

[drain-260712/ADR](../adr/drain-260712-drain-input-buffers-before-turn-start.md) drains input buffers before turn start, [message-260712/ADR](../adr/message-260712-message-profile-during-buffer-preparation.md) resolves message inference settings during preparation, and [consume-260712/ADR](../adr/consume-260712-consume-failed-buffer-items-without-starting-a-turn.md) defines handled preparation failures as consumed and non-turn-producing.

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
