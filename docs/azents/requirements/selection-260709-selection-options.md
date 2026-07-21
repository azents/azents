---
title: "Agent Model Selection Options Historical Requirements Reconstruction"
created: 2026-07-09
implemented: 2026-07-09
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: selection-260709
historical_reconstruction: true
migration_source: "docs/azents/design/model-selection-options.md"
---

# Agent Model Selection Options Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `selection-260709`
- Source: `docs/azents/design/selection-260709-selection-options.md`
- Historical source date basis: `2026-07-09`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently stores the main model and lightweight model directly on each Agent as model selection snapshots. Changing the model requires opening Agent settings, and the chat surface has no constrained model-selection layer that can be reused for per-run model choice, subagent model choice, or future dynamic routing.

The direct-embedded model fields also make it hard to expose a small curated set of models without listing every provider model in the chat UI.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Add an Agent-owned selectable model list that limits which models can be chosen during Agent runs and future subagent spawning.
- Let users edit the Agent selectable model list with a unique label for each entry.
- Let Agent main and lightweight model settings choose by label from the Agent selectable model list.
- Preserve snapshot-based runtime behavior: runtime uses saved model selection snapshots and does not fetch provider catalogs at run time.
- Support ordered model lists so the first entry can be used as the deterministic fallback.
- Limit the Agent selectable model list to at most 10 entries.
- Convert Workspace model settings from direct default model snapshots to a default selectable model list plus default main/lightweight labels.
- Prefill Agent create forms from Workspace default selectable models.
- Create a foundation for later chat-input model selection, subagent model selection, and dynamic model routing.

## Non-goals

- This phase does not add chat composer model switching.
- This phase does not add subagent model selection or model-scope enforcement.
- This phase does not implement dynamic model routing.
- This phase does not introduce a separate model-list table.
- This phase does not add backward compatibility with removed legacy ModelConfig APIs.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
