---
title: "Agent Model Selection Options Design"
created: 2026-07-09
updated: 2026-07-09
implemented: 2026-07-09
tags: [backend, frontend, engine, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: selection-260709
migration_source: "docs/azents/design/model-selection-options.md"
historical_reconstruction: true
---

# Agent Model Selection Options Design

## Problem

Azents currently stores the main model and lightweight model directly on each Agent as model selection snapshots. Changing the model requires opening Agent settings, and the chat surface has no constrained model-selection layer that can be reused for per-run model choice, subagent model choice, or future dynamic routing.

The direct-embedded model fields also make it hard to expose a small curated set of models without listing every provider model in the chat UI.

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

## Current behavior

### Agent model storage

Agents store model snapshots directly:

- `agents.model_selection`
- `agents.lightweight_model_selection`
- `agents.model_parameters`

Runtime resolve reads these Agent snapshots directly. Workspace defaults are only copy sources during Agent create/update and are not consulted at run time.

### Workspace defaults

Workspace model settings currently store:

- `workspace_model_settings.default_model_selection`
- `workspace_model_settings.default_lightweight_model_selection`

Agent creation without explicit model selection copies these defaults into the new Agent.

### Catalog and picker

Model picker reads stored catalog projections through the LLM Provider Integration catalog entry endpoint. Submit paths normalize `{ llm_provider_integration_id, model_identifier }` into a saved `AgentModelSelection` snapshot.

## Proposed design

### Concept: selectable model option

Add an ordered JSON-backed selectable model list to Agents and Workspace model settings.

Each selectable model option has:

- `label`: user-visible unique label within the list.
- `model_selection`: normalized `AgentModelSelection` snapshot.

The list is an array, not an object, because order matters for fallback and UI. Label uniqueness is enforced in the application layer.

Example:

```json
[
  {
    "label": "default",
    "model_selection": {
      "llm_provider_integration_id": "int_...",
      "provider": "openai",
      "model_identifier": "gpt-5",
      "model_display_name": "GPT-5",
      "model_developer": "openai",
      "model_family": "gpt-5",
      "normalized_capabilities": {},
      "model_snapshot": {},
      "source_metadata": null,
      "last_refreshed_at": "2026-07-09T00:00:00Z"
    }
  }
]
```

### Agent model fields

Add Agent model-option fields:

- `selectable_model_options`: JSONB array of selectable model options.
- `main_model_label`: string label selected from `selectable_model_options`.
- `lightweight_model_label`: string label selected from `selectable_model_options`.

The existing `model_selection` and `lightweight_model_selection` columns remain as denormalized effective runtime snapshots:

- `model_selection = option[main_model_label].model_selection`
- `lightweight_model_selection = option[lightweight_model_label].model_selection`

Agent create/update service owns consistency between the label/list fields and the effective snapshot columns. Runtime continues to read the existing effective snapshots and does not resolve labels, query catalogs, or query Workspace defaults during run start. This preserves the current runtime boundary while introducing the label-based model target abstraction for future chat, subagent, and routing features.

### Workspace model settings fields

Add Workspace default model-option fields:

- `default_selectable_model_options`: JSONB array of selectable model options.
- `default_main_model_label`: string label selected from the default selectable model options.
- `default_lightweight_model_label`: string label selected from the default selectable model options.

The existing direct workspace default snapshot columns remain as denormalized effective defaults:

- `default_model_selection = option[default_main_model_label].model_selection`
- `default_lightweight_model_selection = option[default_lightweight_model_label].model_selection`

Workspace settings service owns consistency between the default label/list fields and the effective default snapshot columns. New Agent creation copies the Workspace default selectable model list and labels into the Agent unless the create request supplies an explicit list.

### Invariants

For both Agent and Workspace default lists:

- The list must contain at least 1 entry.
- The list must contain at most 10 entries.
- Labels must be unique within the list.
- Labels must be non-empty after trimming.
- Labels should have a bounded length, recommended 1-80 characters.
- `main_model_label` and `lightweight_model_label` must be labels in the list after normalization.
- If either selected label is absent, it is automatically replaced with the first list entry label.
- If a selected option's underlying model pair changes, all references to that label use the new model snapshot.
- Runtime must not call provider model listing APIs to resolve a label.

### Label identity and rename behavior

Because there is no separate option ID, the label is the option identity.

A label rename is represented as a changed label in the submitted array. The server normalizes the submitted list and selected labels after receiving the full payload:

- If the submitted `main_model_label` exists, keep it.
- Otherwise set `main_model_label` to the first option label.
- If the submitted `lightweight_model_label` exists, keep it.
- Otherwise set `lightweight_model_label` to the first option label.

The UI should update selected labels when it provides an explicit rename interaction for a selected label. The server fallback remains the safety net for delete/rename races and malformed clients.

### Agent create behavior

When creating an Agent:

1. If the request includes `selectable_model_options`, normalize and use it.
2. Otherwise, copy `workspace_model_settings.default_selectable_model_options`.
3. If Workspace defaults are empty or missing, Agent creation fails.
4. Normalize `main_model_label`:
   - request value if valid;
   - otherwise Workspace default main label if it exists in the copied list;
   - otherwise first option label.
5. Normalize `lightweight_model_label` similarly.
6. Write effective main/lightweight snapshots from the selected labels.

The Agent create form preloads the Workspace default selectable model list and default labels so users can edit the list before saving.

### Agent update behavior

Agent update accepts whole-list replacement for selectable model options.

On update:

1. If `selectable_model_options` is provided, normalize the full list.
2. If the normalized list is empty, reject the request.
3. If the list has more than 10 entries, reject the request.
4. Resolve each submitted `{ llm_provider_integration_id, model_identifier }` through stored catalog projection and store the resulting snapshot.
5. Normalize selected labels against the final list.
6. Recompute effective main/lightweight snapshots.

Removing the selected label automatically moves selection to the first option. Reordering the list changes the fallback target but does not change selected labels while they still exist.

### Workspace settings behavior

Workspace model settings update accepts whole-list replacement for `default_selectable_model_options` plus default main/lightweight labels.

Rules:

- A Workspace default model list must contain at least one option once configured.
- The list is capped at 10 entries.
- Labels are unique in app-layer validation.
- Default main/lightweight labels normalize to the first entry when absent or invalid.
- Updating Workspace defaults does not mutate existing Agents.
- New Agents are prefilled from Workspace defaults.

### API shape

#### Shared request shape

For create/update requests, use input model references and labels:

```json
{
  "selectable_model_options": [
    {
      "label": "default",
      "model_selection": {
        "llm_provider_integration_id": "int_...",
        "model_identifier": "gpt-5"
      }
    }
  ],
  "main_model_label": "default",
  "lightweight_model_label": "default"
}
```

The service resolves `model_selection` inputs into stored snapshots.

#### Shared response shape

Responses should include both the selectable model options and effective selected snapshots:

```json
{
  "selectable_model_options": [
    {
      "label": "default",
      "model_selection": { "...": "AgentModelSelection snapshot" }
    }
  ],
  "main_model_label": "default",
  "lightweight_model_label": "default",
  "model_selection": { "...": "effective main AgentModelSelection" },
  "lightweight_model_selection": { "...": "effective lightweight AgentModelSelection" }
}
```

Keeping `model_selection` and `lightweight_model_selection` in responses preserves existing UI summary and runtime callers during migration while exposing the new label-based list.

### Runtime behavior

Runtime resolve continues to receive effective model selections through the existing Agent snapshot columns:

- `agent.model_selection`
- `agent.lightweight_model_selection`

The Agent service owns consistency between labels/list and these effective snapshots. Runtime must never call model catalogs, provider listing APIs, or Workspace defaults to resolve a model label.

### Chat model selection foundation

This phase only exposes the Agent selectable model list through Agent responses. A later phase can add chat composer model selection by choosing one of the Agent labels for a run.

The later per-run input should reference labels, not provider model identifiers. That keeps chat UI constrained to the Agent-owned list and avoids exposing all provider models in the composer.

### Subagent foundation

This phase does not add subagent model selection. However, subagent tooling can later choose from the same Agent selectable model labels.

A future `spawn_agent` extension can accept a model label, and the server can validate it against the parent/root Agent selectable model list before creating the child run configuration.

### Dynamic routing foundation

The selectable model list provides named model targets for future routing policies. A later dynamic routing feature can choose among labels rather than provider-specific model identifiers.

## Error handling

Reject Agent or Workspace settings writes when:

- selectable model option list is empty;
- selectable model option list has more than 10 entries;
- any label is empty after trimming;
- labels are duplicated after normalization;
- any model selection input cannot be resolved through the stored catalog projection;
- selected labels are invalid only when the list is also invalid. Otherwise selected labels are normalized to the first option.

Recommended validation error messages:

- `At least one selectable model is required.`
- `At most 10 selectable models are allowed.`
- `Selectable model labels must be unique.`
- `Selectable model label is required.`
- `Selected model was not found in the model catalog.`

## Security and permissions

No new permission category is required.

- Agent create/update remains governed by existing Agent management permissions.
- Workspace model settings update remains governed by existing Workspace LLM/model settings permissions.
- Model option resolution must verify that each integration belongs to the same workspace and is selectable through stored catalog projection.
- Runtime uses saved snapshots only and does not broaden provider credential access.

## Migration plan

1. Add JSONB fields to Agents and Workspace model settings.
2. Backfill each existing Agent with one selectable model option using the current `model_selection` snapshot.
   - Recommended label: `default`.
   - `main_model_label = "default"`.
   - `lightweight_model_label = "default"` if lightweight equals main; otherwise create a second option such as `lightweight` and select it.
3. Backfill Workspace model settings similarly from current defaults.
4. Update service create/update paths to normalize lists and write effective snapshots.
5. Update API schemas and generated clients.
6. Update Agent form and Workspace model settings UI to edit ordered selectable model lists.
7. Update specs for Agent domain, Model Catalog domain, and execution/runtime behavior as needed.

Migration must not modify already executed migration files.

## Frontend behavior

### Agent create form

- Fetch Workspace default model settings.
- Prefill the Agent model option list with Workspace defaults.
- Allow adding, removing, reordering, and editing entries up to 10.
- Each row has:
  - label input;
  - model picker button;
  - selected model summary;
  - remove control when more than one entry exists.
- Main model and lightweight model selects use labels from the list.
- If a selected label disappears, the UI should select the first label.
- Save is disabled or validation fails when the list is empty or duplicate labels exist.

### Agent edit form

- Render current Agent selectable model list.
- Model row picker reuses the existing `ModelCatalogPicker`.
- Editing a row's model changes all settings that reference that row's label.
- Reordering changes fallback behavior only.

### Workspace model settings

- Replace default model and default lightweight model direct pickers with default selectable model list editor.
- Add main/default lightweight label selects using the Workspace default list.
- Enforce at least one default option.

## Test Strategy

### Backend tests

- Model option normalization:
  - empty list rejected;
  - more than 10 rejected;
  - duplicate labels rejected;
  - whitespace labels rejected;
  - invalid selected labels normalize to first entry;
  - selected label model changes update effective snapshot.
- Agent create:
  - defaults copied from Workspace model list;
  - explicit list overrides Workspace defaults;
  - effective main/lightweight snapshots are written from labels.
- Agent update:
  - removing selected label falls back to first;
  - list reorder preserves valid selected labels;
  - model catalog resolution failure returns existing model-selection error.
- Workspace settings update:
  - default list validation and selected label normalization.
- Runtime resolve:
  - effective snapshots remain the source of `RunRequest`.

### Frontend tests

- Agent form renders model option list.
- Agent form prevents duplicate labels and empty lists.
- Main/lightweight selects update when labels change or disappear.
- Model picker updates the selected row snapshot.
- Workspace settings default list editor mirrors Agent editor behavior.

### E2E tests

- Create Agent from Workspace default model list and send a message successfully.
- Edit Agent model list by changing the selected label's model and confirm later run uses the new effective model in context/run diagnostics or deterministic fixture evidence.
- Delete the selected label and verify fallback to the first option.

## Spec updates required

- `docs/azents/spec/domain/agent.md`
  - Agent model fields and runtime effective selection rules.
  - Workspace model settings default list behavior.
- `docs/azents/spec/domain/model-catalog.md`
  - Submit normalization now resolves selectable model option entries, not only direct main/lightweight fields.
- `docs/azents/spec/flow/agent-execution-loop.md`
  - Clarify that runtime receives effective model selections resolved from Agent selectable model labels.

A separate drift cleanup task should also reconcile the current stale text that says public integration model listing does not use the materialized catalog cache.

## ADR need

An ADR is required during spec promotion because this changes the durable Agent model-selection contract and establishes the long-term label-based model target abstraction used by future per-run selection, subagents, and dynamic routing.

## Resolved decisions

- Store selectable model options as JSONB arrays, not separate tables or JSON objects.
- Enforce unique labels in the application layer after trimming whitespace.
- Treat labels as case-sensitive display identities after trimming.
- Cap both Agent and Workspace selectable model lists at 10 entries.
- Retain existing direct snapshot columns as denormalized effective runtime/default snapshots owned by Agent and Workspace settings services.
- Use the first ordered option as deterministic fallback when a selected label is missing.
