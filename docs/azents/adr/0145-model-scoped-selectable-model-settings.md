---
title: "ADR-0145: Model-Scoped Selectable Model Settings"
created: 2026-07-16
tags: [architecture, backend, frontend, engine, models]
---

# ADR-0145: Model-Scoped Selectable Model Settings

## Context

An Agent owns an ordered `selectable_model_options` list, but configurable input and output token caps
and provider-hosted built-in tools are stored once in Agent-level `model_parameters`. A prompt or
subagent may select any option by label, so the same global settings are applied after the runtime has
selected a different model. Validation is also performed against the Agent's default main model rather
than every selectable target.

Workspace model settings own the default selectable option list copied into new Agents, but cannot attach
the same settings to each default model. The frontend consequently renders token caps and built-in tool
choices outside the model list.

The normalized model capability snapshot already reports provider-hosted tools as semantic identifiers.
Only `web_search` has a complete current path from capability and validation through runtime lowering.
`web_fetch` and `image_generation` are registered as configurable built-in tools without a complete
supported runtime contract. Image-generation event parsing remains necessary for historical and
provider-originated output data and is independent of Agent built-in tool configuration.

## Decision

### Store user intent on each selectable model option

Each stored `SelectableModelOption` owns a `settings` value alongside its label and immutable
`model_selection` snapshot. The initial settings contract contains:

- nullable `context_window_tokens`;
- nullable `max_output_tokens`;
- an explicit list of enabled `BuiltinToolConfig` values.

The settings are Agent or Workspace user intent. They are not embedded in `AgentModelSelection`, because
that object remains a catalog-derived model fact snapshot.

Agent-level `model_parameters` no longer owns `context_window_tokens`, `max_output_tokens`, or
`builtin_tools`. Other advanced parameters and inference-profile behavior, including reasoning effort,
remain outside selectable option settings.

### Use the selected option's settings at runtime

Label resolution returns the complete selected option. Foreground inference uses that option's output cap
and enabled built-in tools. Its context cap participates in effective context-window calculation.

The prepared Session inference state stores the selected option settings together with the immutable model
snapshot, target label, effort, and effective limits. Automatic retry and recovery reuse this settings
snapshot rather than rereading mutable Agent options. A later prepared turn may resolve newer Agent
settings at the existing turn boundary.

The lightweight option's context cap also participates when computing the compaction-safe effective
context window. Compaction summary generation keeps its existing dynamic output budget; a selectable
option's `max_output_tokens` applies when that option is used as a foreground inference target, not as the
internal compaction summarizer.

Agent API effective-context fields continue to describe the default main/lightweight option pair.
Prompt-level and subagent model overrides resolve their own effective context from the selected option.

### Default all supported implemented built-in tools to enabled

When option settings do not explicitly provide a built-in tool list, normalization enables every semantic
tool identifier advertised by the selected model's normalized capability snapshot and implemented by the
runtime. An explicit empty list means the user disabled every available built-in tool.

Only `web_search` remains in the current built-in tool registry. The incomplete `web_fetch` and
`image_generation` configurable tool entries and their validation rules are removed. Future built-in
tools must add the complete capability, validation, runtime lowering, and UI representation path before
they can be advertised or enabled.

Historical/provider-originated image-generation event parsing, attachment materialization, and display
remain. They are not an Agent-configurable built-in tool contract.

### Share the same contract with Workspace defaults

Workspace default selectable model options use the same settings contract. New Agents copy the complete
ordered option list, including settings. Updating Workspace defaults continues not to mutate existing
Agents.

### Replace persisted global settings without a legacy fallback

A forward data migration materializes settings on every existing Agent and Workspace selectable option,
removes unsupported built-in tool identifiers from persisted capabilities and settings, and removes the
three migrated keys from Agent-level `model_parameters`.

Existing Agent token caps are copied to every selectable option because the prior global values applied
regardless of the requested target label. A non-empty existing built-in tool list is intersected with each
option's supported implemented capabilities. When the old list is absent or empty, every supported
implemented tool is enabled to establish the new default.

The API and runtime do not retain a legacy Agent-global fallback for the migrated fields.

### Make model creation lead directly to editing

The model-add action is placed immediately above the model list. A newly created option starts with an
empty label, and the frontend focuses that option's label input after rendering. Each model row exposes a
settings action that opens the model-scoped settings form.

## Consequences

- Settings follow prompt-level and subagent model target changes instead of leaking from the default main
  model.
- Workspace defaults can fully describe the models copied into a new Agent.
- Effective context resolution must consider both selected main and lightweight option settings.
- The selectable model option public API changes and generated clients must be regenerated.
- Existing JSONB data requires a forward migration, and Agent Session inference state gains a JSONB
  settings snapshot for retry and recovery stability.
- Built-in tool availability becomes conservative: a tool is not advertised until its complete runtime
  path exists.
- Removing incomplete configurable tools does not remove historical provider-tool events.

## Alternatives Considered

### Keep Agent-global token and tool settings

Rejected because a label-selected model can have different limits and hosted-tool capabilities from the
default main model.

### Store settings in `AgentModelSelection`

Rejected because it would mix mutable Agent/Workspace intent with an immutable catalog-derived model
snapshot.

### Keep incomplete built-in tools registered but disabled by default

Rejected because capability and validation visibility would continue to imply runtime support that does
not exist.

### Preserve legacy Agent-global fallback fields

Rejected because it creates two authorities for the same setting and makes per-target behavior dependent
on historical payload shape.
