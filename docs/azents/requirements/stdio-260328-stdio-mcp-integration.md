---
title: "stdio MCP Resolve Flow Integration Historical Requirements Reconstruction"
created: 2026-03-28
implemented: 2026-03-28
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: stdio-260328
historical_reconstruction: true
migration_source: "docs/azents/design/stdio-mcp-resolve-integration.md"
---

# stdio MCP Resolve Flow Integration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `stdio-260328`
- Source: `docs/azents/design/stdio-260328-stdio-mcp-integration.md`
- Historical source date basis: `2026-03-28`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

stdio MCP infrastructure (sidecar Pod spec, ConfigMap, Docker support) and GA4 Toolkit Provider are already implemented, but there is no **resolve flow orchestration** connecting them.

Design Phase 1.5 logic where `resolve_agent_tools()` detects stdio-based toolkits, creates sidecar Pod, and injects actual Pod-IP-based server_url into toolkit.

**Current state:**

```
resolve_agent_tools()
├── Phase 1: Toolkit Collection (resolve) ✅
│   └── GA4Provider.resolve() → placeholder localhost:9000
├── (Phase 1.5: stdio detection → sidecar → URL injection) ❌ missing
└── Phase 2: Tool Creation ✅
    └── GA4Toolkit.create_tools() → tries placeholder URL → fails
```

**Target state:**

```
resolve_agent_tools()
├── Phase 1: Toolkit Collection (resolve)
│   └── GA4Provider.resolve() → placeholder URL, stores credentials
├── Phase 1.5: stdio detection → sidecar Pod creation → URL injection (new)
│   ├── resolved.get_stdio_configs() → collect McpStdioToolkitConfig
│   ├── sandbox_manager.get_or_allocate(stdio_configs=...) → create Pod
│   ├── sandbox_manager.get_pod_ip() → get actual IP
│   └── resolved.set_server_url() → inject actual URL
└── Phase 2: Tool Creation
    └── GA4Toolkit.create_tools() → connect to actual Pod IP → succeeds
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
