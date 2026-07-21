---
title: "Sentry Toolkit Historical Decision Reconstruction"
created: 2026-03-27
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: toolkit-260327
historical_reconstruction: true
migration_source: "docs/azents/design/sentry-toolkit.md"
---

# Sentry Toolkit Historical Decision Reconstruction

- Snapshot: `toolkit-260327`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/sentry-toolkit.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### toolkit-260327/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```mermaid
sequenceDiagram
    participant User as User
    participant Agent as Agent
    participant NI as nointern server
    participant Sentry as mcp.sentry.dev/mcp

    Note over User: enable Sentry Toolkit
    User->>NI: run agent
    NI->>NI: resolve() → no token
    NI->>Agent: provide request_authorization tool
    Agent->>User: "Sentry account connection is required"
    User->>NI: OAuth auth complete
    Note over NI: DCR + OAuth code exchange
    NI->>NI: store token in mcp_oauth2_tokens

    User->>NI: run agent again
    NI->>NI: resolve() → token exists
    NI->>Sentry: list_tools (Streamable HTTP)
    Sentry-->>NI: 23 tools
    NI->>NI: filter by enabled_skills
    NI->>Agent: provide filtered tool list
    Agent->>NI: list_issues(query="is:unresolved")
    NI->>Sentry: call_tool (OAuth Bearer)
    Sentry-->>NI: issue list
    NI-->>Agent: result
```

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
