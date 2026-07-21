---
title: "Move Agent Model Selection to Dynamic ModelConfig Structure Historical Requirements Reconstruction"
created: 2026-05-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: dynamic-260516
historical_reconstruction: true
migration_source: "docs/azents/adr/0031-dynamic-llm-model-configs.md"
---

# Move Agent Model Selection to Dynamic ModelConfig Structure Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `dynamic-260516`
- Source: `docs/azents/adr/dynamic-260516-dynamic-llm-configs.md`
- Historical source date basis: `2026-05-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

nointern Agent model selection has so far gone through static global `LLMModel` and provider-specific `LLMProviderModel` catalogs. Workspaces store credential information and provider settings in `LLMProviderIntegration`, but Agents directly reference `llm_provider_integration_id` and `llm_provider_model_id`.

[llm-260513/ADR](../adr/llm-260513-llm-catalog-source.md) adopted a direction where human-managed Admin catalog CRUD is replaced by external/official catalog sync. However, the feature-design process concluded that current product requirements need a higher-level abstraction than simple catalog sync.

- Model lists differ by workspace integration credential/config, such as Bedrock, Vertex AI, ChatGPT OAuth, and custom account/project/region settings.
- Provider listing sources vary by provider: models.dev, official API, cloud provider API, etc. Listing results are hard to stabilize as operational catalog identity.
- If Agents directly reference provider/model, changes such as default model, lightweight/summary model, coding model, and quota failover must be repeatedly applied to every Agent.
- If listing/cache rows become Agent FK targets, ephemeral discovery results become persistent domain identity, and provider listing changes propagate into DB referential integrity problems.

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
