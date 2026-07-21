---
title: "Move LLM Model Catalog to External Sources and Local Overrides"
created: 2026-05-13
tags: [architecture, backend, api, frontend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: llm-260513
historical_reconstruction: true
migration_source: "docs/azents/adr/0030-llm-model-catalog-source.md"
---

# llm-260513/ADR: Move LLM Model Catalog to External Sources and Local Overrides

> 📌 **Related design document**: [llm-260513-llm-catalog-source.md](../design/llm-260513-llm-catalog-source.md)

## Context

nointern currently manages LLM models through three layers: `LLMModel`, `LLMProviderModel`, and `LLMProviderIntegration`. `LLMProviderIntegration`, managed by Workspace Owners, is clearly workspace-specific credential information. However, the global model catalog, `LLMModel` and `LLMProviderModel`, is directly managed through Admin CRUD.

This creates the following problems:

1. Model lists and provider-specific model identifiers change quickly, and manual Admin CRUD cannot keep up with official/external catalogs.
2. Capabilities used by runtime and frontend are distributed across fields such as `LLMProviderModel.thinking`, `metadata.supported_builtin_tools`, and `metadata.max_input_tokens`. Operators can adjust these values with arbitrary JSON patches, making drift likely among external source, backend, frontend, and runtime.
3. Admin UI exposes `LLM Models` and `Provider Models` management screens, assuming an operational model where humans continuously edit model lists.
4. Agents reference `llm_provider_model_id` and integration id, so provider model identity must remain stable even if the catalog is rebuilt.

Hermes/OpenClaw-like systems use catalog/capability metadata owned by providers/plugins as runtime contracts. OpenCode also imports many provider catalogs through AI SDK and Models.dev while keeping local config/custom provider overrides separately. nointern should move in the same direction.

## Decision

Move the source of truth for nointern's model catalog to **external catalogs / official provider adapters + local overrides**.

Specifically:

1. **Switch catalog source of truth**
   - Use Models.dev as the primary catalog.
   - For providers where the external catalog is insufficient, add adapters for the provider official API or provider documentation.
   - Add internal test models, temporary models, and custom endpoints that are not in external/official sources only through `local override`.

2. **Remove/deprecate manual Admin model CRUD**
   - Deprecate the operational model where Admin directly creates, edits, and deletes `LLMModel` / `LLMProviderModel`.
   - Remove model management screens from Admin UI.
   - If needed, an operations screen can show catalog sync status and readonly diffs, but it must not replace manual CRUD.

3. **Normalize capability internal contract**
   - Do not use the `thinking` column and arbitrary `metadata` patches as the direct contract for capability judgment.
   - Normalize external catalog/adapter results into nointern's internal typed capability contract.
   - Runtime, agent form, built-in tool selection, and context compaction all read this internal contract.
   - Provider-specific raw metadata may be preserved for auditing/debugging, but must not be the source of truth for runtime decisions.

4. **Maintain provider model identity stability**
   - Sync should update/upsert existing `(provider, model_identifier)` records as much as possible so existing Agents' `llm_provider_model_id` references do not break.
   - Models removed from the catalog are not immediately deleted; transition them to unavailable/deprecated state.
   - Deletion is considered only when there are no remaining references and operators approve a separate cleanup policy.

## Consequences

### Positive

- Model lists are managed as reproducible catalogs from external/official sources, not as Admin data edited by humans.
- Capabilities converge into one typed contract used by backend/frontend/runtime.
- Admin surface and operational mistake risk are reduced.
- Catalog freshness can improve while preserving provider model ids.

### Negative

- New operational components are required: catalog sync job, source adapters, and local override merge policy.
- Cache/fallback policy is needed for external catalog outage or delay.
- Provider-specific semantic differences not covered by external catalogs must be supplemented by adapters and local overrides.

### Migration

- The design document PR does not change code or spec.
- In actual implementation, block write paths before immediately deleting existing Admin CRUD, then verify that sync results reproduce existing records reliably.
- Extract existing `thinking`, `metadata.supported_builtin_tools`, and `metadata.max_input_tokens` values as initial local override candidates, but move the final runtime contract to normalized capabilities.

## Alternatives

### 1. Keep current Admin CRUD

- Pros: smaller implementation change and preserves existing operational habits.
- Cons: does not solve model growth rate or capability drift.
- Reason rejected: contradicts the core requirement to move to external/official sources and remove Admin model management.

### 2. Use only external catalog with no local override

- Pros: simpler data flow.
- Cons: no way to handle catalog omissions, custom endpoints, temporary provider-specific limits, or hotfixes during rollout.
- Reason rejected: operational exceptions are necessary, but they must be separated from the source catalog so drift can be tracked.

### 3. Continue using existing `metadata` JSONB as capability patch

- Pros: smaller DB migration.
- Cons: it is unclear which keys are runtime contracts, and frontend/runtime can keep depending on arbitrary keys.
- Reason rejected: does not satisfy the requirement to fix capability divergence.

## Migration provenance

- Historical source filename: `0030-llm-model-catalog-source.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
