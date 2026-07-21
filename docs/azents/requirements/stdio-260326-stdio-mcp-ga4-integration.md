---
title: "stdio MCP Infrastructure + Google Analytics Toolkit Integration Historical Requirements Reconstruction"
created: 2026-03-26
implemented: 2026-03-26
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: stdio-260326
historical_reconstruction: true
migration_source: "docs/azents/design/stdio-mcp-ga4-integration.md"
---

# stdio MCP Infrastructure + Google Analytics Toolkit Integration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `stdio-260326`
- Source: `docs/azents/design/stdio-260326-stdio-mcp-ga4-integration.md`
- Historical source date basis: `2026-03-26`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Build infrastructure to use stdio-based MCP servers in nointern, and integrate Google Analytics 4 as first stdio MCP Toolkit.

**Two tasks as one feature:**
1. **stdio MCP infrastructure** — add mcp-proxy sidecar to Agent Home Pod
2. **GA4 Toolkit** — first consumer of the infrastructure

**Problems solved:**
- Existing MCP toolkit supports only HTTP-based servers. Cannot connect stdio MCP servers (`analytics-mcp`, etc.).
- mcp-proxy sidecar converts stdio → HTTP, reusing existing McpBasedToolkit code.
- GA4 does not support Google Hosted Remote MCP (`analyticsdata.googleapis.com/mcp` → 404).

**User scenarios (GA4):**
1. "Show page views for last 7 days" → `run_report`
2. "How many active users now?" → `run_realtime_report`
3. "Show GA4 property list" → `get_account_summaries`

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
