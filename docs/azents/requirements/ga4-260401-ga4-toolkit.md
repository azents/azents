---
title: "GA4 stdio MCP -> Native Toolkit Migration Historical Requirements Reconstruction"
created: 2026-04-01
implemented: 2026-04-01
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: ga4-260401
historical_reconstruction: true
migration_source: "docs/azents/design/ga4-native-toolkit.md"
---

# GA4 stdio MCP -> Native Toolkit Migration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `ga4-260401`
- Source: `docs/azents/design/ga4-260401-ga4-toolkit.md`
- Historical source date basis: `2026-04-01`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Current Google Analytics 4 toolkit is based on stdio MCP (`analytics-mcp`) + mcp-proxy sidecar. Convert it to native Python toolkit to remove sandbox dependency and cold start.

**Current structure (stdio MCP):**

```mermaid
sequenceDiagram
    participant Engine as Engine (Worker Pod)
    participant Proxy as mcp-proxy sidecar
    participant MCP as analytics-mcp (stdio)
    participant GA as Google Analytics API

    Engine->>Proxy: HTTP SSE (tools/list, tools/call)
    Proxy->>MCP: stdio (JSON-RPC)
    MCP->>GA: REST/gRPC
    GA-->>MCP: Response
    MCP-->>Proxy: stdio
    Proxy-->>Engine: HTTP SSE
```

**After migration (native):**

```mermaid
sequenceDiagram
    participant Engine as Engine (Worker Pod)
    participant Toolkit as GA4 Native Toolkit
    participant GA as Google Analytics API

    Engine->>Toolkit: Direct Python call
    Toolkit->>GA: google-analytics-data / google-analytics-admin SDK
    GA-->>Toolkit: SDK Response objects
    Toolkit-->>Engine: Formatted result
```

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
