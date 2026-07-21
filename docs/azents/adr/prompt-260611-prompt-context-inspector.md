---
title: "System Prompt Context Inspector Preserves Pre-assembly Fragment Metadata"
created: 2026-06-11
tags: [chat, observability, engine, frontend, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: prompt-260611
historical_reconstruction: true
migration_source: "docs/azents/adr/0055-system-prompt-context-inspector.md"
---

# prompt-260611/ADR: System Prompt Context Inspector Preserves Pre-assembly Fragment Metadata

## Context

Azents has a Context tab for session diagnostics, but it cannot show the system prompt delivered to the model. This makes it hard to diagnose whether project instructions, memory instructions, runtime instructions, toolkit status prompt, or interface additional prompt were included in an actual run.

Canonical runtime currently assembles model system prompt from multiple transient sources.

- Agent prompt stored in Agent row and passed as `RunRequest.agent_prompt`
- Interface-level `additional_system_prompt` appended before execution after `RunRequest.agent_prompt`
- Subagent suffix appended after subagent run's agent prompt during subagent execution
- Toolkit prompt fragments returned by each toolkit's `update_context()` result
- Turn-start injected prompt from runtime hooks
- Final assembled system prompt passed to model adapter

Several toolkit provider modules define `system_prompt` metadata for toolkit catalog/API display. This metadata is not the same as runtime prompt delivered to the model. Actual runtime prompt evidence is `ToolkitState.prompt` returned by resolved toolkit instance.

Toolkit prompt can contain several logical sub-prompts. For example, builtin/runtime toolkit prompt can include memory instructions, root `AGENTS.md`, runtime file guidance, registered project list, project `AGENTS.md`, allowed domains, and denied domains. However, the current common contract returns only one `ToolkitState.prompt` string, so toolkit-internal sub-prompts do not remain as stable structured data.

## Decision

### prompt-260611/ADR-D1: Preserve prompt fragment metadata before final string assembly

System prompt analysis does not parse the final assembled string. Instead, preserve prompt fragments with source metadata before joining them into the final string.

First implementation analysis units are:

- agent prompt
- toolkit prompt
- turn injected prompt
- final assembled system prompt

Toolkit prompt remains a single toolkit-level string in the first implementation. Toolkit-internal sub-prompts are not split.

### prompt-260611/ADR-D2: Do not use provider-level toolkit `system_prompt` as runtime prompt evidence

Context Inspector does not use `ToolkitProvider.system_prompt` as evidence for “prompt delivered to the model.” This value may be useful for toolkit management UI or catalog metadata, but system prompt analysis must report runtime `ToolkitState.prompt` collected from resolved toolkit binding.

### prompt-260611/ADR-D3: Exclude toolkit-internal sub-prompt decomposition from this scope

First implementation shows one prompt entry for each toolkit binding that produced non-empty prompt. It does not split builtin/runtime toolkit prompt into memory, root AGENTS, runtime files, registered projects, project AGENTS, domain section, and similar parts.

If stable sub-prompt analysis becomes necessary, add structured prompt parts to runtime contract instead of parsing headings from strings.

### prompt-260611/ADR-D4: Expose turn injected prompt as debug event, not primary system prompt navigation

Turn injected prompt is part of final system prompt. Therefore, collect it as system prompt analysis data and include it in final assembled prompt.

However, do not make it an independent item in System Prompt primary navigation. The Context tab already has a debug event list, so represent turn-start hook injection as debug event. This keeps primary System Prompt navigation focused on agent prompt and toolkit prompt.

### prompt-260611/ADR-D5: Show long prompt content through drill-down navigation

System Prompt UI does not expand every prompt text by default on one page. Provide drill-down navigation: Context → System Prompt → agent prompt, toolkit prompt list, final prompt, individual prompt detail.

List items show metadata and short preview only. Full prompt text appears only in detail view.

## Considered options

### Option A — Parse final system prompt string

Pros:

- Minimal backend changes.
- Can implement with only current final string value.

Cons:

- Prompt headings are not stable protocol and are fragile.
- Toolkit ownership cannot be known reliably.
- After strings are merged, agent/toolkit/injected sources cannot be reliably separated.
- Does not fit debugging surface that must explain inclusion/omission causes.

### Option B — Preserve toolkit prompt metadata when generating tool catalog

Pros:

- Provides stable toolkit ownership metadata.
- Matches first UI goal of showing prompt grouped by toolkit.
- Avoids final string parsing.
- Keeps `ToolkitState` contract.

Cons:

- Requires runtime catalog data structure change.
- Cannot show toolkit-internal sub-prompts.

### Option C — Add structured prompt parts to `ToolkitState`

Pros:

- Can reliably show internal structure of builtin/runtime prompt.
- Best fit if prompt substructure becomes a product requirement long term.

Cons:

- Large cross-toolkit contract change.
- Larger scope than first implementation goal.
- Must decide how every toolkit describes prompt substructure.

## Consequences

- Context tab can show whether agent prompt, toolkit prompt, turn injected prompt, and final prompt existed in a run.
- Toolkit prompt entries have stable source metadata, but internal sections remain raw text.
- AGENTS-related debugging can start by checking whether runtime toolkit prompt includes project instruction text.
- Turn injected prompt is visible in debug event and final prompt detail but does not complicate primary System Prompt navigation.
- Future structured toolkit sub-prompt parts can be added while preserving top-level navigation model.

## Migration provenance

- Historical source filename: `0055-system-prompt-context-inspector.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
