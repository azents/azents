---
title: "System Prompt Context Inspector Preserves Pre-assembly Fragment Metadata Historical Requirements Reconstruction"
created: 2026-06-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: prompt-260611
historical_reconstruction: true
migration_source: "docs/azents/adr/0055-system-prompt-context-inspector.md"
---

# System Prompt Context Inspector Preserves Pre-assembly Fragment Metadata Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `prompt-260611`
- Source: `docs/azents/adr/prompt-260611-prompt-context-inspector.md`
- Historical source date basis: `2026-06-11`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

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
