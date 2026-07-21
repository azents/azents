---
title: "Agent Model Selection Stores Catalog Snapshot Directly Without ModelConfig"
created: 2026-06-16
tags: [architecture, backend, api, frontend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: selection-260616
historical_reconstruction: true
migration_source: "docs/azents/adr/0063-agent-model-selection-snapshot.md"
---

# selection-260616/ADR: Agent Model Selection Stores Catalog Snapshot Directly Without ModelConfig

## Context

[dynamic-260516/ADR](./dynamic-260516-dynamic-llm-configs.md) removed Agent runtime dependency on static `LLMModel` / `LLMProviderModel` catalog and introduced workspace-level `ModelConfig` alias/preset as Agent model selection contract. This structure provided dynamic model listing and workspace default preset, but actual product usage still had these problems:

- When creating Agent, user ultimately chooses one model from catalog, but has to create and manage a separate `ModelConfig` entity in the middle.
- Alias semantics where `ModelConfig` changes immediately affect referencing Agents are convenient, but make it hard to predict when an Agent setting changed to which model.
- Merging `ModelConfig.default_parameters` and `Agent.model_parameter_overrides` splits ownership of advanced settings in two.
- Workspace default model is necessary, but reusable preset CRUD complicates Agent create/edit UX.
- `ModelConfig` API, repository, service, frontend router, and migration/backfill path became excessive layers compared with runtime selection.

Therefore, simplify model selection again. Catalog remains as listing source for selectable models, but Agent runtime contract becomes model selection snapshot stored in Agent row, without referencing a separate `ModelConfig` row.

## Decision

### selection-260616/ADR-D1. Remove `ModelConfig` entity

Remove `model_configs` table, `ModelConfigRepository`, `ModelConfigService`, public `/model-config/v1` API, and frontend model-config router/UI.

Agent create/edit/run paths no longer accept or store `model_config_id` or `lightweight_model_config_id`.

### selection-260616/ADR-D2. Agent stores main/lightweight model selection snapshots directly

Agent row directly stores main model snapshot and lightweight model snapshot.

Snapshot includes at least these runtime-required fields:

- provider
- `llm_provider_integration_id`
- provider runtime `model_identifier`
- display name
- model developer/vendor
- normalized capabilities
- source/listing metadata

Catalog/listing row is not an FK target. Agent stores the snapshot verified and normalized by server at submit time.

### selection-260616/ADR-D3. Advanced model parameters move to Agent settings

Remove existing merge structure between `ModelConfig` default parameters and `Agent.model_parameter_overrides`.

Agent has single `model_parameters` setting, and runtime normalizes this value by capability and uses it directly.

### selection-260616/ADR-D4. Workspace stores default model snapshot

Workspace has these settings:

- default model selection snapshot
- optional default lightweight model selection snapshot

If default lightweight model is empty, effective lightweight default is default model.

### selection-260616/ADR-D5. Workspace default is submit-time copy source, not runtime inheritance

When Agent create/edit submits with empty main model, copy workspace default model snapshot into Agent.

When Agent create/edit submits with empty lightweight model, copy into Agent in this order:

1. workspace default lightweight model snapshot
2. Agent main model snapshot

After copy, Agent is independent from workspace default. Changing workspace default does not affect existing Agent snapshot.

### selection-260616/ADR-D6. Define bootstrap rule for workspace default main model

If workspace default main model does not exist and Agent is submitted with empty main model, fail.

If workspace default main model does not exist and Agent is created with explicit main model, server sets that snapshot as workspace default main model.

Once set, workspace default main model cannot be deleted and can only be changed. Workspace default lightweight model can be empty.

### selection-260616/ADR-D7. Remove subagent model inherit mode

Subagent also has the same model snapshot fields as Agent. Following parent model is handled as copy at subagent create/edit time, not runtime inheritance.

Remove `AgentModelConfigInheritMode` and `model_config_inherit_mode`.

### selection-260616/ADR-D8. Do not keep legacy compatibility path

This change is a clean migration.

- Remove `model_config_id`, `lightweight_model_config_id`, `model_config_inherit_mode`, and `effective_model_config_id` from API request/response.
- Remove `ModelConfig` lookup from runtime fallback.
- Replace existing `ModelConfig`-based tests/API/client paths with new snapshot-based paths.
- Migration backfills existing data into new Agent/Workspace snapshots and then drops legacy columns/table.

## Consequences

### Positive

- Agent settings screen has simpler UX where users directly select catalog model.
- Runtime model resolve becomes simpler: Agent row + Integration lookup.
- Advanced setting owner is unified into Agent.
- Workspace default only works as starting point for new Agents, improving predictability of existing Agents.
- Removing `ModelConfig` CRUD/API/frontend layers reduces maintenance surface.

### Negative / Trade-offs

- Alias/preset operations pattern for changing model of multiple Agents at once disappears.
- Workspace default changes are not automatically reflected in existing Agents, so separate bulk update feature is needed if necessary.
- Drift can occur between Agent snapshot and current catalog listing. This drift should be handled by UI diagnostics without changing runtime source of truth.
- Migration is large because existing `ModelConfig` references must be copied into Agent snapshots.

## Alternatives

### Keep `ModelConfig` and hide only in UI

Rejected. Complexity in API/runtime/advanced settings remains, and it becomes a hidden entity invisible to user.

### Agent references workspace default at runtime

Rejected. Workspace default changes would implicitly change existing Agent execution result, reducing predictability.

### Reference catalog row as Agent FK

Rejected. Provider listing can vary by account/project/region/credential, and using ephemeral discovery row as persistent runtime identity increases drift and cleanup problems.

### Keep `ModelConfig` as reduced global preset

Rejected. Goal of this decision is removing model selection layer. If presets become necessary, design a separate Agent snapshot bulk-update feature.

## Related Documents

- [llm-260513/ADR: Organize LLM model catalog source](./llm-260513-llm-catalog-source.md)
- [dynamic-260516/ADR: Migrate Agent model selection to dynamic ModelConfig structure](./dynamic-260516-dynamic-llm-configs.md)
- [Dynamic LLM ModelConfig architecture design](../design/dynamic-llm-model-configs.md)

## Migration provenance

- Historical source filename: `0063-agent-model-selection-snapshot.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
