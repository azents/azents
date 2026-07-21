---
title: "GitHub Toolkit Historical Requirements Reconstruction"
created: 2026-03-13
implemented: 2026-03-22
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: github-260313
historical_reconstruction: true
migration_source: "docs/azents/design/github-toolkit.md"
---

# GitHub Toolkit Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `github-260313`
- Source: `docs/azents/design/github-260313-github-toolkit.md`
- Historical source date basis: `2026-03-13`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Service Toolkit based on GitHub MCP server. Implement as a single `github` ToolkitType supporting multiple authentication methods by extending `McpBasedToolkitProvider`.

```mermaid
graph TD
    subgraph "GitHubToolkitProvider"
        Config["GitHubToolkitConfig<br/>(auth_type, toolsets)"]
        Secrets["GitHubSecrets (Union)<br/>PAT | App BYOA | App Platform"]
    end

    Config --> Resolve["resolve()"]
    Secrets --> Resolve

    Resolve -->|PAT| Bearer1["Bearer token<br/>(passed as-is)"]
    Resolve -->|App BYOA| JWT["JWT → installation token"]
    Resolve -->|App Platform| JWT2["JWT (server PEM) → installation token"]
    Resolve -->|Per-User PAT| PerUser["Fetch per-user PAT from DB"]

    Bearer1 --> MCP["GitHub MCP server<br/>api.githubcopilot.com/mcp/"]
    JWT --> MCP
    JWT2 --> MCP
    PerUser --> MCP
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
