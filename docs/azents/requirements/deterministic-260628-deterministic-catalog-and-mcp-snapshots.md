---
title: "Deterministic Tool Catalog, MCP Tool Snapshots, and Stable Toolkit Prompts Historical Requirements Reconstruction"
created: 2026-06-28
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: deterministic-260628
historical_reconstruction: true
migration_source: "docs/azents/adr/0085-deterministic-tool-catalog-and-mcp-snapshots.md"
---

# Deterministic Tool Catalog, MCP Tool Snapshots, and Stable Toolkit Prompts Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `deterministic-260628`
- Source: `docs/azents/adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md`
- Historical source date basis: `2026-06-28`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents sends model-visible tools through the Responses API top-level `tools` field. This is distinct from Codex's internal `additional_tools` input item used by its Responses Lite path. `additional_tools` does not solve cache instability by itself: changing any model-visible tool schema or order still changes the provider-facing request prefix.

The current optimization problem is that Azents' model-visible tool catalog can be non-deterministic even when the user-facing toolkit configuration has not changed. Provider prompt caches are sensitive to tool schema and order, so the same session can lose cache locality when the tool array changes unnecessarily.

Known instability sources include:

- MCP-based toolkits returning tools in external server order.
- MCP tool discovery completing after the first run has already started.
- MCP loading/error states changing model-visible tools, such as exposing a retry tool.
- GitHub multi-installation MCP tools becoming available at different times.
- Goal or Todo tools regressing into state-dependent visibility.
- Provider-hosted tools preserving upstream order when multiple hosted tools are present.
- Final `ToolCatalog.native_tools` preserving upstream insertion order rather than applying a canonical order.
- Toolkit prompts embedding transient state such as MCP loading/error state, current Goal state, or current Todo list.

A previous Azents implementation waited for MCP tool lists on every user input. That made runs very slow, with responses delayed by more than a minute when MCP servers were slow or unstable. MCP server availability must therefore not become a synchronous dependency for normal run startup.

System prompt stability matters for the same cache locality reason as tool schema stability. Azents assembles model instructions from the agent prompt, toolkit prompt fragments, and turn-injected hook prompts. The agent prompt and configuration-derived toolkit prompts are expected to change when configuration changes. Transient toolkit state should not be injected into the system prompt unless it is deliberately part of the agent instruction model.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Goal toolkit tools should remain model-visible regardless of the current goal state. State-specific behavior should be handled by tool execution and prompt text, not by adding/removing goal tools from the catalog.

Todo toolkit tools should likewise remain model-visible regardless of whether the current todo list is empty or populated. Todo state may change the prompt fragment and UI snapshot, but it must not change the tool definition set.

This keeps the provider-facing tool list stable across normal Goal/Todo state transitions.

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
