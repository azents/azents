---
title: "Model-Scoped Subagent Override Policy Historical Requirements Reconstruction"
created: 2026-07-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: subagent-260717
historical_reconstruction: true
migration_source: "docs/azents/adr/0166-subagent-model-override-policy.md"
---

# Model-Scoped Subagent Override Policy Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `subagent-260717`
- Source: `docs/azents/adr/subagent-260717-subagent-override-policy.md`
- Historical source date basis: `2026-07-17`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

An Agent owns an ordered `selectable_model_options` list. The `spawn_agent` tool dynamically exposes those Agent-owned labels as optional model target overrides, while omission of `model_target_label` inherits the concrete parent Session inference profile.

Every selectable option is currently advertised as a subagent override. This gives the model no Agent-owner policy for avoiding an unusually expensive target and no task-specific guidance for preferring a lightweight target. A parent model can therefore delegate broad or exploratory work to a high-cost model even when a cheaper model is the intended subagent choice.

The policy must distinguish explicit target selection from profile inheritance. A model excluded from the override list may still be the active parent model, and inherited child execution must remain valid.

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
