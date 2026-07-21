---
title: "Manage Toolkit Lifecycle by AgentSession Lifecycle Historical Requirements Reconstruction"
created: 2026-05-29
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: toolkit-260529
historical_reconstruction: true
migration_source: "docs/azents/adr/0040-session-scoped-toolkit-lifecycle.md"
---

# Manage Toolkit Lifecycle by AgentSession Lifecycle Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `toolkit-260529`
- Source: `docs/azents/adr/toolkit-260529-toolkit-lifecycle.md`
- Historical source date basis: `2026-05-29`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[dynamic-260329/ADR](../adr/dynamic-260329-dynamic-tools.md) introduced the Toolkit State Machine and decided that toolkit background work lifecycle should be scoped to `_SessionRunner`. The engine reads only current state through `update_context()` on each turn, while heavy work such as MCP connection and tool listing should be managed by the toolkit in the background.

Current implementation does not fully satisfy this decision. The worker calls `resolve_agent_tools()` on every message to create new toolkit instances, and `_SessionRunner` calls `__aenter__()` on the toolkit list returned from the first run only after the canonical engine calls `update_context()`. Therefore, the first run executes `update_context()` without `__aenter__()`, causing MCP-based toolkits to take sync fallback. In later runs, newly resolved toolkit instances are not under `__aenter__()`/`__aexit__()` management.

This cannot be fixed merely by moving `__aenter__()` earlier. Some toolkits capture a mix of state that is safe to reuse for a session and state that changes per run.

- MCP/AWS/GCP toolkits are well-suited for session-scoped background connection state.
- `ScheduleToolkit` captures the full `ToolkitContext` in the constructor, so `run_id`, `publish_event`, and `user_id` can become stale.
- Subagent tool wrapper captures `parent_run_id`, `parent_check_stop`, `publish_event`, and `user_id` at run time.
- MCP per-user OAuth and GitHub per-user PAT select tokens by `user_id` at resolve time, so if actor changes inside a session, stale credential risk appears.

[hook-260518/ADR](../adr/hook-260518-hook.md) runtime hook system also uses Toolkit as the runtime capability provider boundary. Provider list and hook ordering depend on resolved toolkit snapshot, so session-scoped toolkit reuse must clearly separate hook provider snapshot from per-run hook context.

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
