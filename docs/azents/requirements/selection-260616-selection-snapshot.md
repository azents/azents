---
title: "Agent Model Selection Stores Catalog Snapshot Directly Without ModelConfig Historical Requirements Reconstruction"
created: 2026-06-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: selection-260616
historical_reconstruction: true
migration_source: "docs/azents/adr/0063-agent-model-selection-snapshot.md"
---

# Agent Model Selection Stores Catalog Snapshot Directly Without ModelConfig Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `selection-260616`
- Source: `docs/azents/adr/selection-260616-selection-snapshot.md`
- Historical source date basis: `2026-06-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[dynamic-260516/ADR](../adr/dynamic-260516-dynamic-llm-configs.md) removed Agent runtime dependency on static `LLMModel` / `LLMProviderModel` catalog and introduced workspace-level `ModelConfig` alias/preset as Agent model selection contract. This structure provided dynamic model listing and workspace default preset, but actual product usage still had these problems:

- When creating Agent, user ultimately chooses one model from catalog, but has to create and manage a separate `ModelConfig` entity in the middle.
- Alias semantics where `ModelConfig` changes immediately affect referencing Agents are convenient, but make it hard to predict when an Agent setting changed to which model.
- Merging `ModelConfig.default_parameters` and `Agent.model_parameter_overrides` splits ownership of advanced settings in two.
- Workspace default model is necessary, but reusable preset CRUD complicates Agent create/edit UX.
- `ModelConfig` API, repository, service, frontend router, and migration/backfill path became excessive layers compared with runtime selection.

Therefore, simplify model selection again. Catalog remains as listing source for selectable models, but Agent runtime contract becomes model selection snapshot stored in Agent row, without referencing a separate `ModelConfig` row.

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
