---
title: "Subagent Model Override Policy"
created: 2026-07-17
updated: 2026-07-17
tags: [agent, backend, frontend, engine, subagent, models]
---

# Subagent Model Override Policy

## Problem

`spawn_agent` currently advertises every Agent-owned selectable model label as an explicit subagent model target. This provides no model-scoped policy for excluding an unusually expensive model or steering exploratory work toward a lightweight model.

The model list is prompt guidance, not an enforcement boundary. Because `model_target_label` is a free string, hiding a label without changing validation would still allow a stale, guessed, or hallucinated tool call to select that model.

At the same time, an option excluded from explicit selection may be the model already executing the parent turn. Default subagent creation must continue to inherit that concrete parent profile.

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

## Current Behavior

Each `SelectableModelOption` owns a label, immutable model-selection snapshot, and `SelectableModelSettings`. The settings object contains model-scoped token caps and enabled provider-hosted tools. The complete selected settings object is also stored in the prepared `AgentSession` inference state.

`SubagentToolkit._spawn_agent_description()` iterates over the owning Agent's current `selectable_model_options` and renders every label plus its supported reasoning efforts. Explicit `model_target_label` validation independently resolves against the same unfiltered option list. Omitting the label inherits the parent Session inference state.

Workspace default selectable model options share the Agent option contract and are copied into newly created Agents.

## Proposed Design

### Model settings contract

Extend both input and stored `SelectableModelSettings` shapes:

```json
{
  "context_window_tokens": null,
  "max_output_tokens": null,
  "builtin_tools": [],
  "subagent_enabled": true,
  "subagent_guidance": null
}
```

Semantics:

- `subagent_enabled` controls only explicit `model_target_label` selection by `spawn_agent`.
- Input omission defaults `subagent_enabled` to `true`.
- `subagent_guidance` is nullable and limited to 500 characters.
- Omitted, null, empty, or whitespace-only guidance normalizes to null.
- Stored settings and API responses always contain both fields explicitly.
- Guidance is Agent-owner-authored parent-model routing guidance. It is not part of the child task or child system prompt.

The existing settings object is deliberately used rather than adding an option-level policy object. This keeps model editing, Workspace defaults, copy behavior, API mapping, and generated clients on one model-settings contract. Session inference state receives a redundant copy of the fields, but that copy is not authoritative for subagent routing.

### Dynamic `spawn_agent` description

Build one eligible override list from options whose `settings.subagent_enabled` is true. For each eligible option, render:

- the Agent-owned label;
- supported reasoning-effort values;
- `subagent_guidance` when present.

Example model-visible content:

```text
Available model target overrides
(optional; inherited parent Run target is preferred):
- `pro` Reasoning efforts: medium, high.
  Guidance: Use only when the task requires maximum synthesis quality; this target is expensive.
- `luna` Reasoning efforts: low, medium.
  Guidance: Prefer for repository exploration, code search, and bounded investigation.
```

Guidance lines are indented under their label so multiline text cannot become an unrelated list item. Null guidance produces no guidance line.

When no option is enabled, render a short statement that no explicit model target override is available and that omission of `model_target_label` inherits the parent profile.

The description continues not to expose physical model data.

### Spawn validation

Use the same eligibility predicate for description construction and explicit override resolution.

- `model_target_label` omitted: inherit the parent model target even when that option is disabled.
- `reasoning_effort` provided without a target label: retain the inherited parent model and validate only the requested effort.
- `model_target_label` provided: resolve only among enabled options.
- Missing or disabled labels fail before child identity, Session, or pending run creation.
- Explicitly naming a disabled label is rejected even if it matches the inherited parent label. The caller must omit the label to inherit.
- Existing full-history fork restrictions remain unchanged.

Use a generic model-visible error stating that the label is not available for explicit subagent override. The error does not need to distinguish missing from disabled because both mean the requested override is outside the advertised contract.

Eligibility is read from the current owning Agent on every spawn request. A policy update therefore affects later spawn calls immediately. Existing children and `followup_task` continue using their Session inference state and are not invalidated.

### Agent and Workspace behavior

Agent create/update and Workspace model settings use the same settings input normalization.

- A newly added option defaults to enabled with null guidance.
- Changing the physical model assigned to an existing label preserves subagent policy.
- Workspace defaults store the policy and copy it into new Agents.
- Updating Workspace defaults does not modify existing Agents.
- Reordering or renaming options preserves the policy attached to the edited option object.

### Settings UI

Add a Subagents subsection to the existing per-model settings modal after execution settings.

Controls:

1. **Available for explicit subagent selection** — switch, enabled by default.
2. **Subagent selection guidance** — optional text area, maximum 500 characters.

Utility copy explains that:

- enabled options are shown to the parent model as explicit `spawn_agent` targets;
- disabling the option does not prevent a child from inheriting the active parent model;
- guidance should describe appropriate task types or cost/quality constraints.

When the switch is off, the guidance text area is disabled but its value is preserved so re-enabling restores the prior text. The field is submitted as null when blank. The UI uses the same component for Agent settings and Workspace defaults.

Add Storybook states for enabled guidance and disabled explicit selection. Preserve the existing modal layout and responsive behavior.

## API and Data Model Changes

Affected public schemas:

- `SelectableModelSettingsInput`
  - `subagent_enabled: bool = true`
  - `subagent_guidance: str | null = null`, maximum 500 characters
- `SelectableModelSettings`
  - required `subagent_enabled: bool`
  - required nullable `subagent_guidance: str | null`, maximum 500 characters

Because these types are nested in Agent and Workspace model settings APIs, regenerate the public OpenAPI document and Python/TypeScript clients.

No new table or column is required. The fields live in existing JSONB values.

## Migration and Rollout

Generate a new Alembic revision. Do not modify any executed migration.

The migration updates these JSONB shapes:

- every option in `agents.selectable_model_options`;
- every option in `workspace_model_settings.default_selectable_model_options` when present;
- `agent_sessions.current_model_settings` when present.

Materialize:

```json
{
  "subagent_enabled": true,
  "subagent_guidance": null
}
```

Existing behavior is therefore preserved. Application code uses the complete new stored shape and retains no legacy missing-field fallback after the migration.

The migration does not change current Agent defaults, Session model targets, running child trees, or provider configuration.

## Error Handling

- Guidance longer than 500 characters is rejected by request validation.
- Whitespace-only guidance normalizes to null.
- Disabled or unknown explicit target labels fail the tool call before durable child creation.
- Inheritance remains available even when all explicit targets are disabled.
- The existing reasoning-effort validation and fork/profile validation ordering remains intact.

## Security and Prompt Safety

Guidance is written by users already authorized to edit the Agent or Workspace model settings. Those users can already control Agent system prompts and toolkit configuration, so guidance does not introduce a new trust tier.

The 500-character limit bounds prompt growth. The maximum ten-option list contributes at most 5,000 guidance characters. Rendering guidance under the corresponding option keeps its scope legible. The runtime continues to expose only Agent-owned labels and effort values, not credentials or provider details.

## Test Strategy

### E2E primary verification matrix

| Scenario | Expected result |
|---|---|
| Enabled lightweight option with guidance | Explicit spawn succeeds with the selected lightweight model |
| Disabled expensive option explicitly requested | Tool call fails and no child node is created |
| Parent currently uses a disabled option and omits target | Child is created with the inherited parent profile |
| Parent uses disabled option and supplies effort only | Child retains inherited model and applies valid requested effort |
| All options disabled | Spawn without target succeeds; every explicit target fails |
| Workspace default policy copied to new Agent | Created Agent returns the same enabled/guidance values |
| Policy changed after child creation | Existing child follow-up remains valid; later spawn uses updated policy |

Extend the deterministic subagent/per-prompt profile E2E path. It already owns model-target spawn coverage and credential-free model fixtures. No external credentials or new prerequisite snapshot is required.

### Web Surface E2E

Use the real Agent or Workspace model settings surface to:

1. open one model's settings;
2. disable explicit subagent selection;
3. enter guidance on another option;
4. save and reload;
5. verify both settings persist.

This test belongs in the required credential-free web-surface lane. Missing application readiness is a failure, not a skip.

### Backend tests

- settings input and stored-shape defaults/validation;
- guidance trimming and length rejection;
- Agent/Workspace normalization and round-trip persistence;
- dynamic description filtering and guidance rendering;
- disabled explicit-target rejection;
- disabled inherited-target success;
- effort-only inherited-target success;
- no child rows or wake-up publication after rejected override;
- migration upgrade assertions for Agent, Workspace, and Session JSONB.

### Frontend tests and stories

- stored-option to form-value mapping and request mapping;
- new-option defaults;
- physical-model replacement preserves subagent policy;
- Zod 500-character validation;
- settings modal enabled/disabled interaction;
- Storybook states for guidance and disabled selection;
- localized utility copy in every supported locale.

### CI execution

Run required backend Ruff, formatting, Pyright, and pytest checks; TypeScript formatting, lint, typecheck, build, and web tests; deterministic E2E; web-surface E2E; OpenAPI/client generation verification; and docs index validation.

No live/external test is needed. No scenario is optional or credential-dependent.

## Implementation Areas

- Core model settings types and normalization
- Agent/Workspace JSONB migration
- Subagent tool description and override validation
- Agent and Workspace public API/client regeneration
- Agent model settings form, localization, tests, and stories
- Deterministic subagent E2E and web-surface E2E
- Agent domain, toolkit domain, and agent execution-loop specs

## Alternatives Considered

### Prompt-only filtering

Rejected because a free-string tool call could still select a hidden expensive model.

### Block disabled models from inheritance

Rejected because the policy controls optional target selection, not the concrete parent profile inherited by default.

### Store a separate option-level policy object

Rejected in favor of the existing model settings contract and UI. The Session snapshot receives a small unused copy, while routing remains authoritative from the current Agent settings.

### Structured cost and task categories

Deferred. Freeform bounded guidance directly supports cost warnings and task recommendations without defining a premature routing taxonomy.

## Open Questions

None. The user-visible requirements and persistence boundary are resolved.
