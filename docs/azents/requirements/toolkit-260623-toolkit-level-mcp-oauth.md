---
title: "Replace MCP Per-User OAuth with Toolkit-Level OAuth Connections Historical Requirements Reconstruction"
created: 2026-06-23
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: toolkit-260623
historical_reconstruction: true
migration_source: "docs/azents/adr/0071-toolkit-level-mcp-oauth.md"
---

# Replace MCP Per-User OAuth with Toolkit-Level OAuth Connections Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `toolkit-260623`
- Source: `docs/azents/adr/toolkit-260623-toolkit-level-mcp-oauth.md`
- Historical source date basis: `2026-06-23`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently supports MCP per-user OAuth through `auth_type=oauth2_per_user`. That path stores one OAuth token per `(toolkit_id, user_id)` in `mcp_oauth2_tokens`, emits MCP authorization request events when a user has not connected, and disables per-user OAuth toolkits in system sessions.

The product direction is to remove this per-user MCP OAuth surface and make OAuth a toolkit-level connection. Notion, Sentry, and generic remote MCP toolkits should use the same OAuth authorization code + PKCE flow, optionally with Dynamic Client Registration (DCR), but the resulting connection belongs to the `ToolkitConfig` rather than to an individual user.

The change intentionally changes authorization semantics:

- Old behavior: each user connects their own external account.
- New behavior: workspace managers connect the toolkit once, and agent runs using that toolkit use the toolkit's OAuth connection.

This reduces runtime branching, removes user-specific MCP authorization request events, makes OAuth usable from system sessions, and makes Notion/Sentry work as manager-configured service integrations.

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
