---
title: "ADR-0031: Move Agent Model Selection to Dynamic ModelConfig Structure"
created: 2026-05-16
tags: [architecture, backend, api, frontend, engine]
---

# ADR-0031: Move Agent Model Selection to Dynamic ModelConfig Structure

Related design document: [dynamic-llm-model-configs.md](../design/dynamic-llm-model-configs.md)

## Context

nointern Agent model selection has so far gone through static global `LLMModel` and provider-specific `LLMProviderModel` catalogs. Workspaces store credential information and provider settings in `LLMProviderIntegration`, but Agents directly reference `llm_provider_integration_id` and `llm_provider_model_id`.

ADR-0030 adopted a direction where human-managed Admin catalog CRUD is replaced by external/official catalog sync. However, the feature-design process concluded that current product requirements need a higher-level abstraction than simple catalog sync.

- Model lists differ by workspace integration credential/config, such as Bedrock, Vertex AI, ChatGPT OAuth, and custom account/project/region settings.
- Provider listing sources vary by provider: models.dev, official API, cloud provider API, etc. Listing results are hard to stabilize as operational catalog identity.
- If Agents directly reference provider/model, changes such as default model, lightweight/summary model, coding model, and quota failover must be repeatedly applied to every Agent.
- If listing/cache rows become Agent FK targets, ephemeral discovery results become persistent domain identity, and provider listing changes propagate into DB referential integrity problems.

## Decision

Move nointern Agent model selection to workspace-level **`ModelConfig` alias/preset**.

Specifically:

1. **Remove static catalog**
   - Stop managing `LLMModel` and `LLMProviderModel` as static global/provider catalogs for nointern Agent model selection.
   - Remove existing `llm_models`, `llm_provider_models`, catalog sync, Admin/public model catalog APIs, and frontend `llm-provider-model` router from this feature.
   - Do not reuse `llm_provider_models` as discovery cache. If cache is needed later, design a new table that Agents or ModelConfigs do not reference.

2. **Dynamic provider listing**
   - Agent settings UX first selects provider integration, then calls provider-specific dynamic model listing with that integration's credential/config.
   - Provider implementation decides listing source, such as models.dev, provider official API, AWS Bedrock API, Google Vertex AI API, or provider-specific hardcoded selector.
   - Listing results are ephemeral and are not Agent/ModelConfig FK targets.
   - Listing adapters expose only normalized models that satisfy the nointern runtime contract. Models that fail normalization are excluded from user-visible lists and reported in skip summary.

3. **Introduce ModelConfig**
   - Workspace owns reusable `ModelConfig` records.
   - `ModelConfig` stores label, provider integration FK, provider, model identifier, display name, developer, family, normalized capabilities, runtime snapshot, source metadata, default flags, enabled flag, and default parameters.
   - `ModelConfig` is a logical slot/preset, so provider integration and model can change during update.
   - `ModelConfig` updates immediately affect all Agent runtimes that reference it.

4. **Agents reference ModelConfig alias**
   - Agents do not directly select provider/model; they reference `model_config_id`.
   - Lightweight/summary use is represented by separate FK `lightweight_model_config_id`.
   - Existing `model_parameters.compaction_model_id` is removed and replaced by `lightweight_model_config_id`.
   - Runtime parameters merge `ModelConfig.default_parameters` and `Agent.model_parameter_overrides`, with Agent override winning.

5. **Make subagent model inherit explicit**
   - Subagents represent model inheritance through `model_config_inherit_mode` enum: `inherit | custom`.
   - `role=agent` is always stored as `custom` and requires `model_config_id`.
   - `role=subagent, inherit` must have both model config FKs null and inherits parent main / lightweight config.
   - `role=subagent, custom` requires `model_config_id`; `lightweight_model_config_id=null` means use custom main as lightweight as well.

6. **Preserve patch meaning**
   - Updates to `default_parameters` and `model_parameter_overrides` are whole-object replace, not nested patch.
   - Field omission means unchanged; explicit `null` means set null; object means replace the entire object.
   - To remove an individual override key, send the full object again without that key.

7. **Include only minimal safeguards**
   - Audit/history is out of scope for this feature.
   - Deletion of a referenced ModelConfig is blocked.
   - Disabled ModelConfig hard-fails at runtime.
   - UI may show referencing Agent count and provider change warnings.

## Consequences

### Positive

- Workspace Owner first connects provider credential/config and then selects only models actually available from that integration.
- Agents reference stable aliases, so default/coding/lightweight/quota failover changes can be handled in one ModelConfig.
- Ephemeral provider listing is separated from persistent runtime configuration.
- Static global catalog operations, sync drift, and provider model FK stability problems are removed.

### Negative

- Migration must convert existing Agent direct provider/model references into shared ModelConfig references.
- Provider listing adapters are responsible for runtime-required normalization, so provider implementation quality directly affects user-visible options.
- Listing cache is out of scope, so listing API and auto-create are sensitive to provider/source call failures. Existing Agent runtime still works from stored ModelConfig snapshot.

### Migration

- Create one shared `ModelConfig` inside each workspace for every existing `(llm_provider_integration_id, llm_provider_model_id)` combination. Do not create one config per Agent.
- Existing Agents with the same combination reference the same ModelConfig.
- Select default model from the most-used migrated config.
- Select default lightweight model by prioritizing existing compaction usage if present; otherwise use provider-specific selector.
- After migration completes, remove existing provider/model direct FKs from Agent and remove static catalog tables in the same feature.
- Actual implementation Alembic migration files must be generated with `alembic revision` according to repository convention.

## Alternatives

### 1. Keep ADR-0030 external catalog sync structure

- Pros: keeps global catalog, so existing Agent FK structure changes less.
- Cons: does not solve model lists varying by integration credential/config or workspace preset requirements.
- Reason rejected: the feature goal is to stop using static global/provider catalogs and make Agents reference ModelConfig aliases.

### 2. Reuse `llm_provider_models` as discovery cache

- Pros: can reuse existing table and some repository code.
- Cons: high risk that ephemeral listing/cache rows become FK targets again or get mixed with previous static catalog semantics.
- Reason rejected: discovery/cache is not persistent runtime config identity. If needed, it should be separated into a new table.

### 3. Copy model snapshot directly into Agent

- Pros: Agent runtime is simpler without ModelConfig table.
- Cons: default/failover/lightweight changes must be repeatedly applied to every Agent; shared preset UX cannot be built.
- Reason rejected: conflicts with the requirement that ModelConfig updates immediately affect referencing Agents.

### 4. Store integration + dynamic model identifier directly on Agent without ModelConfig

- Pros: creation form changes are relatively small.
- Cons: no workspace-level alias, default model, quota failover, or shared parameter preset.
- Reason rejected: nointern's operational unit is workspace preset, not individual Agent model.

### 5. Use nested patch to update only some parameter override keys

- Pros: UI request can be small when changing one key.
- Cons: omission/null meaning becomes complex again, and removing override vs setting null gets confused.
- Reason rejected: follow patch convention by keeping field omission and explicit null meanings clear.

### 6. Implement audit/history together

- Pros: can track ModelConfig change history and Agent impact.
- Cons: greatly expands the data model/API/runtime migration scope of this feature.
- Reason rejected: this feature is about moving to alias/preset structure. Audit/history needs separate decision and UX.
