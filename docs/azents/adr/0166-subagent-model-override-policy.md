---
title: "ADR-0166: Model-Scoped Subagent Override Policy"
created: 2026-07-17
tags: [architecture, agent, backend, frontend, engine, subagent, models]
---

# ADR-0166: Model-Scoped Subagent Override Policy

## Context

An Agent owns an ordered `selectable_model_options` list. The `spawn_agent` tool dynamically exposes those Agent-owned labels as optional model target overrides, while omission of `model_target_label` inherits the concrete parent Session inference profile.

Every selectable option is currently advertised as a subagent override. This gives the model no Agent-owner policy for avoiding an unusually expensive target and no task-specific guidance for preferring a lightweight target. A parent model can therefore delegate broad or exploratory work to a high-cost model even when a cheaper model is the intended subagent choice.

The policy must distinguish explicit target selection from profile inheritance. A model excluded from the override list may still be the active parent model, and inherited child execution must remain valid.

## Decision

Each Agent-owned selectable model option will carry subagent override policy with these semantics:

- explicit subagent override availability defaults to enabled;
- disabled options are omitted from the model target override list rendered in the dynamic `spawn_agent` tool description;
- disabled options remain usable when `spawn_agent` omits `model_target_label` and inherits the parent Session inference profile;
- each option may carry optional model-selection guidance for the parent model, such as cost warnings or recommended task categories;
- guidance is rendered only with that option in the dynamic `spawn_agent` model target list;
- Workspace default selectable options carry and copy the same policy into newly created Agents;
- existing Agents and Workspace defaults are migrated to explicit enabled availability with no guidance, preserving current behavior.

Explicit override validation uses the same filtered option set as the dynamic tool description. Supplying a disabled option through `model_target_label` fails even if the label exists on the Agent. Omitting `model_target_label` remains the inheritance path. A reasoning-effort-only override also remains an inheritance path because it retains the parent model target. If no option is enabled, the tool advertises no explicit model target overrides while inherited spawning remains available.

The policy is evaluated from the owning Agent's current selectable options when each spawn is requested. Disabling an option does not terminate an existing child or prevent later `followup_task` work in that child Session.

The policy controls model-visible explicit subagent target selection. It does not change normal Agent default selection, prompt-level model selection, lightweight compaction selection, provider capabilities, or physical model snapshots.

### Store the policy in selectable model settings

Extend the existing `SelectableModelSettings` contract with:

- `subagent_enabled: bool`;
- `subagent_guidance: str | None`.

The input contract defaults an omitted `subagent_enabled` to `true` and omitted or null `subagent_guidance` to null. The stored and response contract materializes both fields explicitly.

This treats `settings` as the complete user-configurable policy for one selectable model option rather than only provider execution parameters. The complete settings object continues to be snapshotted into `AgentSession` inference state. The copied subagent fields are not runtime inference authority: dynamic `spawn_agent` description and explicit override validation always read the owning Agent's current selectable option settings.

Keeping the policy in the existing settings object preserves a simple model-settings API and UI. It accepts a small redundant copy in Session inference state instead of introducing a separate option-level policy shape.

### Render bounded guidance in the dynamic tool description

`subagent_guidance` is parent-model selection guidance, not a prompt injected into the child. Input is trimmed, whitespace-only input normalizes to null, and non-null guidance is limited to 500 characters. The bound limits the dynamic tool-description contribution to 5,000 guidance characters across the maximum ten selectable options.

For every enabled option, the dynamic model target list renders the label, supported reasoning efforts, and guidance when present. Guidance is omitted entirely when null. Disabled options contribute neither a list entry nor guidance. When no option is enabled, the description states that no explicit model target override is available and directs the model to omit `model_target_label` to inherit the parent profile.

The settings UI places these controls in the existing per-model settings modal:

- an enabled-by-default switch for explicit subagent selection;
- a nullable guidance text area with the 500-character limit;
- explanatory copy that disabling explicit selection does not block parent-profile inheritance.

Changing the physical model selected by an existing option preserves its subagent policy because the policy describes the Agent-owned label's routing role. Creating a new option initializes enabled availability and null guidance.

### Apply the same settings contract to Agent and Workspace options

Agent selectable options and Workspace default selectable options use the same complete settings shape. Workspace settings copy the policy into newly created Agents, and later Workspace changes do not mutate existing Agents. The forward migration materializes `subagent_enabled = true` and `subagent_guidance = null` for existing Agent options, Workspace default options, and Agent Session model-settings snapshots. Runtime retains no legacy missing-field fallback after migration.

## Consequences

- `spawn_agent` prompt construction and override validation must use the same filtered option set.
- Inheritance remains independent from explicit override eligibility.
- Agent and Workspace model settings APIs and generated clients will change.
- The model settings UI will expose availability and optional guidance for each selectable option.
- Persisted Agent and Workspace selectable option JSON and existing Agent Session model-settings snapshots require a forward migration to the complete stored shape.

## Alternatives Considered

### Disable the model for all subagent execution

Rejected because a parent already running on that model must still be able to create a child through the default parent-profile inheritance path.

### Add only static global subagent guidance

Rejected because cost and task suitability are properties of the selectable target and must remain attached to the target label shown to the model.

### Hide disabled options without validating explicit overrides

Rejected in principle because prompt visibility alone is not an authorization boundary. The final design must define deterministic validation against the same eligibility policy used by the tool description.
