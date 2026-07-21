---
title: "Subagent Model Override Policy Historical Requirements Reconstruction"
created: 2026-07-17
implemented: 2026-07-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: override-260717
historical_reconstruction: true
migration_source: "docs/azents/design/subagent-model-override-policy.md"
---

# Subagent Model Override Policy Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `override-260717`
- Source: `docs/azents/design/override-260717-subagent-override-policy.md`
- Historical source date basis: `2026-07-17`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

`spawn_agent` currently advertises every Agent-owned selectable model label as an explicit subagent model target. This provides no model-scoped policy for excluding an unusually expensive model or steering exploratory work toward a lightweight model.

The model list is prompt guidance, not an enforcement boundary. Because `model_target_label` is a free string, hiding a label without changing validation would still allow a stale, guessed, or hallucinated tool call to select that model.

At the same time, an option excluded from explicit selection may be the model already executing the parent turn. Default subagent creation must continue to inherit that concrete parent profile.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Let each selectable model option opt out of explicit subagent model selection.
- Keep explicit override visibility and validation consistent.
- Preserve parent-profile inheritance when the active parent model is excluded.
- Let Agent owners provide concise target-specific selection guidance, including cost warnings and recommended task categories.
- Apply the same model settings contract to Agent options and Workspace default options.
- Preserve current behavior for existing data by migrating every option to enabled with no guidance.

## Non-goals

- Blocking an excluded model from normal Agent execution, human prompt-level selection, or lightweight compaction.
- Terminating existing child Sessions when settings change.
- Adding cost calculation, automatic model routing, or structured cost tiers.
- Exposing provider names, physical model identifiers, pricing, or catalog metadata in the subagent toolkit.
- Injecting model guidance into the child subagent prompt.
- Adding profile overrides to `followup_task`.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
