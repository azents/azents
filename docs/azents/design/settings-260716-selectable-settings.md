---
title: "Model-Scoped Selectable Model Settings"
created: 2026-07-16
updated: 2026-07-16
tags: [backend, frontend, engine, models, migration, e2e, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: settings-260716
migration_source: "docs/azents/design/model-scoped-selectable-model-settings.md"
historical_reconstruction: true
---

# Model-Scoped Selectable Model Settings

## Problem

Selectable Agent models may differ in input limits, output limits, and provider-hosted tool support.
Azents currently stores the corresponding user intent once in Agent-level `model_parameters`, so a
prompt-selected or subagent-selected model receives settings chosen for a different target. Workspace
default model options cannot carry these settings, and the Agent form renders the controls away from the
model they configure.

Adding a model also appends a row below the viewport while leaving focus on the add button. The generated
label starts with a system-selected value such as `default`, even though the user owns label semantics.

## Goals

- Store max context window, max output tokens, and enabled built-in tools per selectable model option.
- Apply the settings for the label-selected foreground model in all runtime paths.
- Include the same settings in Workspace default model options copied into new Agents.
- Enable every supported and implemented built-in tool by default while preserving an explicit all-off
  choice.
- Remove configurable built-in tools that do not have a complete runtime implementation.
- Put model configuration behind a row-level settings modal.
- Move the add action next to the list, create an empty label, and focus the new label input.

## Non-Goals

- Moving reasoning effort into model option settings. Reasoning effort remains part of the current
  inference-profile behavior.
- Applying a model option's max output cap to internal compaction summary generation.
- Propagating later Workspace default changes into existing Agents.
- Reimplementing image generation or web fetch.
- Removing historical image-generation event parsing or attachment rendering.
- Adding provider-specific built-in tool configuration fields to the first UI version.

## Current Behavior

`SelectableModelOption` contains a label and resolved `AgentModelSelection`. Agent-global
`ModelParameters` contains context and output caps plus built-in tool declarations. Agent create/update
validates built-in tools only against the effective default main selection. Runtime label resolution may
replace the main model snapshot, but it continues reading the global parameters.

Effective context is the minimum of the main model input limit, lightweight model input limit, and the
single Agent context cap. Subagent model overrides separately repeat that calculation with the same global
cap.

The Agent form and Workspace default model card share `SelectableModelOptionsEditor`. The add action is in
the title row, while the rendered sortable option list follows the main/lightweight selectors. Newly added
labels are generated from `default`, `lightweight`, and `option-N` candidates.

The built-in tool registry contains `web_search`, `web_fetch`, and `image_generation`; only `web_search`
is lowered into a provider-native LiteLLM Responses request. Image-generation output events are parsed in
the event adapter independently from Agent configuration.

## Data Model

### Core types

Add a model-scoped settings contract:

```python
class SelectableModelSettings(BaseModel):
    context_window_tokens: int | None
    max_output_tokens: int | None
    builtin_tools: list[BuiltinToolConfig]
```

Stored options always contain concrete settings:

```python
class SelectableModelOption(BaseModel):
    label: str
    model_selection: AgentModelSelection
    settings: SelectableModelSettings
```

Input options accept omitted settings as the product-level request for defaults derived from the resolved
model capability. An explicit `builtin_tools: []` remains distinct and disables all built-in tools.

`ModelParameters` removes `context_window_tokens`, `max_output_tokens`, and `builtin_tools`. Its remaining
fields retain their current meaning.

### Form values

Each `SelectableModelOptionFormValue` carries nullable token caps and an enabled built-in tool list. Model
replacement resets settings to null token caps and every supported implemented built-in tool. Stored
values are not recomputed while editing unless the user replaces the model.

### Persistence

Agent and Workspace option arrays remain JSONB whole-list replacement contracts. The denormalized
`model_selection` and `lightweight_model_selection` columns remain model facts without settings.

`agent_sessions` gains a nullable `current_model_settings` JSONB snapshot beside
`current_model_selection`. Prepared inference states always write both values together. Automatic retry
and recovery read the Session-owned snapshot so later Agent edits cannot change an already prepared turn.

## API Behavior

Agent create/update and Workspace model settings update accept model-scoped settings on every selectable
option. Services first resolve the submitted model selection through the stored catalog, then normalize
settings against that resolved capability.

Normalization rules:

- omitted settings use null token caps and all supported implemented built-in tools;
- explicit null token caps mean no user cap;
- positive token caps are stored as user intent even when larger than catalog limits;
- an omitted built-in tool list enables all supported implemented tools;
- an explicit empty list disables all tools;
- duplicate or unsupported tool names are rejected;
- unknown configuration fields are rejected.

Agent responses return stored option settings. Agent-global migrated fields are absent from
`model_parameters`.

## Runtime Resolution

Label resolution returns the selected option rather than only its `model_selection`. Prepared Session
inference state stores `option.settings` with the selected model snapshot. Retry and recovery rebuild the
request from both Session-owned snapshots; they do not rematch mutable Agent options.

For foreground inference:

- provider/model/credentials/capabilities come from `option.model_selection`;
- `max_output_tokens` and built-in tools come from `option.settings`;
- the main input limit is the minimum of the model capability limit and the option context cap when set.

For compaction-safe context calculation:

- resolve the selected foreground option's capped input limit;
- resolve the Agent lightweight option's capped input limit;
- use the smaller value as the effective context window;
- compute the automatic compaction threshold from that value.

The internal compaction summary keeps its dynamic output budget. Agent response effective-context fields
use the default main/lightweight options. Prompt preparation, run recovery, and subagent model overrides
continue storing the resolved effective context in Session inference state.

## Built-in Tool Availability

The current configurable registry contains only `web_search`. `web_fetch` and `image_generation` rules and
registry entries are removed because they lack a complete supported runtime contract.

Capability projection filters semantic tool IDs through the implemented registry. Future tools must add:

1. normalized catalog capability projection;
2. validation rule;
3. runtime request lowering and response handling as applicable;
4. localized UI presentation and optional configuration form;
5. runtime and E2E coverage.

The settings modal renders the model capability list generically. Known tool IDs use localized labels;
unknown IDs cannot reach stored settings because backend capability validation rejects unregistered tools.

## Frontend Interaction

Each model row has a settings button alongside change-model and remove actions. The modal shows:

- max context window;
- max output tokens;
- one switch or checkbox per supported implemented built-in tool.

The form indicates the catalog capability limits but token inputs remain user intent and may exceed them;
runtime clamping remains authoritative.

The add button moves from the title row to immediately above the sortable option list. Adding an option:

1. creates a stable ID and empty label;
2. initializes no model selection and default empty settings until a model is chosen;
3. appends the option;
4. focuses the new label input after React commits the controlled form update.

Selecting a model initializes null token caps and enables every supported implemented built-in tool.

The shared editor provides identical behavior in Agent settings and Workspace default model settings.

## Migration and Rollout

A new forward migration transforms existing JSONB data; executed migrations remain unchanged.

The migration:

- removes `web_fetch` and `image_generation` from normalized capability snapshots in current catalog
  entries, Agent effective selections, Agent option selections, Workspace effective selections, Workspace
  option selections, and Session current selections;
- removes both names from Agent-global built-in tool lists;
- adds the nullable Session model-settings snapshot column and backfills every prepared Session from its
  current model snapshot and the owning Agent's old global values;
- creates settings for every Agent option;
- copies an Agent's old context and output caps to every option;
- maps a non-empty old built-in tool list to each option by intersecting it with that option's supported
  implemented tools;
- when the old list is absent or empty, enables all supported implemented tools for each option;
- creates Workspace option settings with null token caps and all supported implemented tools enabled;
- removes migrated keys from Agent `model_parameters` and stores null when no parameters remain.

The migration is intentionally not reversible because removed tool capability and user-intent provenance
cannot be reconstructed safely.

Deployment requires the migration and backend/client/frontend changes to ship as one coordinated feature.
There is no runtime fallback to Agent-global token or built-in tool settings.

## Error Handling

- Empty/duplicate labels and missing models continue to block save.
- Non-positive token values block save.
- Unsupported or duplicate built-in tool IDs block save with option-local errors.
- A model removed from the live catalog remains editable from its stored snapshot until the user chooses a
  replacement, preserving the existing snapshot behavior.
- Runtime retains defensive capability validation for stale or direct requests.

## Security and Permissions

Permissions do not change. Agent admins/owners manage Agent model settings, and Workspace owners manage
Workspace defaults. Tool settings contain no credentials; provider credentials remain integration-scoped.

## Test Strategy

### E2E primary validation matrix

| Surface | Scenario | Expected result |
|---|---|---|
| Agent model settings | Add model on mobile-width viewport | Empty label row appears, scrolls into view through focus, and receives keyboard focus |
| Agent model settings | Open row settings | Modal shows token fields and only capability-supported implemented tools |
| Agent model settings | Select web-search-capable model | Web search starts enabled and can be explicitly disabled |
| Agent model settings | Save distinct values on two labels | Reload preserves each row's independent settings |
| Runtime | Send prompts with two model labels | Each foreground call uses that label's output cap and tool list |
| Runtime context | Switch to option with smaller context cap | Prepared Session profile reports the smaller effective context and threshold |
| Workspace defaults | Save option settings and create Agent | New Agent receives the complete option settings copy |
| Removed tools | Load migrated Agent/catalog data | Web fetch and image generation are not offered as configurable tools |

### Backend and unit coverage

- option normalization defaults and explicit-empty tool semantics;
- validation against each option's resolved capability;
- Agent and Workspace repository JSON round trips;
- default-copy behavior;
- foreground run resolution and subagent override context calculation;
- catalog projection filtering;
- migration upgrade fixture covering Agent, Workspace, catalog, and Session JSONB shapes.

### Frontend and Storybook coverage

- shared editor stories for default, pending model, modal open, token values, no supported tools, and multiple
  supported tool fixtures;
- component interaction coverage for add/focus, modal edits, model replacement defaults, and explicit
  all-off built-in tools;
- responsive desktop and mobile visual review.

### Fixtures and prerequisites

The deterministic model catalog fixture needs at least one `web_search`-capable model and one model without
built-in tools. E2E must not require live provider credentials. Runtime request assertions should use the
deterministic/local provider capture path; live-provider checks remain optional and must skip when
credentials are absent.

### Evidence and CI policy

Record backend test commands, TypeScript format/lint/typecheck/build, generated-client diff checks, E2E
commands, viewport, and screenshots for the modal and focused mobile row. Deterministic E2E failures block
shipping. Optional live-provider checks may skip only with an explicit missing-credential reason.

## Alternatives Considered

- Keep Agent-global settings: rejected because selected labels can represent incompatible models.
- Store settings inside the model snapshot: rejected because mutable user intent must not alter catalog
  facts.
- Advertise incomplete tools as disabled: rejected because visible capability still implies support.
- Reuse a global settings modal: rejected because it obscures which model owns the values.
