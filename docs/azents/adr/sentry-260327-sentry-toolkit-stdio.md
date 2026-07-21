---
title: "Sentry Toolkit — access_token Mode (stdio via mcp-proxy) Historical Decision Reconstruction"
created: 2026-03-27
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: sentry-260327
historical_reconstruction: true
migration_source: "docs/azents/design/sentry-toolkit-stdio.md"
---

# Sentry Toolkit — access_token Mode (stdio via mcp-proxy) Historical Decision Reconstruction

- Snapshot: `sentry-260327`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/sentry-toolkit-stdio.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### sentry-260327/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```mermaid
sequenceDiagram
    participant Admin as Admin
    participant Agent as Agent
    participant NI as nointern server
    participant Proxy as mcp-proxy sidecar
    participant MCP as @sentry/mcp-server (stdio)

    Admin->>NI: Create Sentry Toolkit<br/>(access_token)

    Agent->>NI: Run agent
    NI->>NI: resolve() → access_token
    NI->>Proxy: list_tools (HTTP)
    Proxy->>MCP: stdio: tools/list
    MCP-->>Proxy: 23 tools
    Proxy-->>NI: HTTP response
    NI->>NI: Filter by enabled_skills
    NI->>Agent: Filtered tool list
    Agent->>NI: list_issues(query="is:unresolved")
    NI->>Proxy: call_tool (HTTP)
    Proxy->>MCP: stdio: list_issues
    MCP-->>Proxy: Issue list
    Proxy-->>NI: HTTP response
    NI-->>Agent: Result
```

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
