---
title: "MCP Toolkit Historical Requirements Reconstruction"
created: 2026-02-28
implemented: 2026-03-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: mcp-260228
historical_reconstruction: true
migration_source: "docs/azents/design/mcp-toolkit.md"
---

# MCP Toolkit Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `mcp-260228`
- Source: `docs/azents/design/mcp-260228-mcp-toolkit.md`
- Historical source date basis: `2026-02-28`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Integrate MCP (Model Context Protocol) server as nointern Toolkit so agent can use tools from external MCP servers.

## Primary Actor

Current `ToolkitProvider` has tool list fixed at class level with `tool_names: ClassVar[list[str]]`. MCP Toolkit needs interface change because tool list must vary depending on config and context:

- each MCP server provides different tools
- per-user auth toolkit must not provide tools in system context (scheduled run, etc.)

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
