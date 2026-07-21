---
title: "Move LLM Model Catalog to External Sources and Local Overrides Historical Requirements Reconstruction"
created: 2026-05-13
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: llm-260513
historical_reconstruction: true
migration_source: "docs/azents/adr/0030-llm-model-catalog-source.md"
---

# Move LLM Model Catalog to External Sources and Local Overrides Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `llm-260513`
- Source: `docs/azents/adr/llm-260513-llm-catalog-source.md`
- Historical source date basis: `2026-05-13`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

nointern currently manages LLM models through three layers: `LLMModel`, `LLMProviderModel`, and `LLMProviderIntegration`. `LLMProviderIntegration`, managed by Workspace Owners, is clearly workspace-specific credential information. However, the global model catalog, `LLMModel` and `LLMProviderModel`, is directly managed through Admin CRUD.

This creates the following problems:

1. Model lists and provider-specific model identifiers change quickly, and manual Admin CRUD cannot keep up with official/external catalogs.
2. Capabilities used by runtime and frontend are distributed across fields such as `LLMProviderModel.thinking`, `metadata.supported_builtin_tools`, and `metadata.max_input_tokens`. Operators can adjust these values with arbitrary JSON patches, making drift likely among external source, backend, frontend, and runtime.
3. Admin UI exposes `LLM Models` and `Provider Models` management screens, assuming an operational model where humans continuously edit model lists.
4. Agents reference `llm_provider_model_id` and integration id, so provider model identity must remain stable even if the catalog is rebuilt.

Hermes/OpenClaw-like systems use catalog/capability metadata owned by providers/plugins as runtime contracts. OpenCode also imports many provider catalogs through AI SDK and Models.dev while keeping local config/custom provider overrides separately. nointern should move in the same direction.

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
