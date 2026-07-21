---
title: "stdio MCP Infrastructure + Google Analytics Toolkit Integration Historical Decision Reconstruction"
created: 2026-03-26
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: stdio-260326
historical_reconstruction: true
migration_source: "docs/azents/design/stdio-mcp-ga4-integration.md"
---

# stdio MCP Infrastructure + Google Analytics Toolkit Integration Historical Decision Reconstruction

- Snapshot: `stdio-260326`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/stdio-mcp-ga4-integration.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### stdio-260326/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```
Worker Pod                               Agent Home Pod
┌──────────────────────────┐            ┌──────────────────────────────────┐
│ Engine                   │            │ sandbox container                │
│ ├─ resolve_agent_tools   │            │ ├─ sandbox-daemon               │
│ │  ├─ detect stdio toolkit│           │ └─ mitmproxy + socat            │
│ │  └─ ensure_ready (eager)│           │                                  │
│ │                        │  HTTP SSE  │ mcp-proxy sidecar               │
│ ├─ GA4ToolkitProvider    │ ────────→  │ ├─ :9000                        │
│ │  └─ McpBasedToolkit    │ Pod IP     │ ├─ /servers/ga4/sse             │
│ │     (existing code)    │            │ └─ analytics-mcp (subprocess)   │
│ └────────────────────────┘            │    └─ SA Key via Secret mount   │
└──────────────────────────┘            └──────────────────────────────────┘
```

From Engine perspective, there is no difference between stdio MCP and HTTP MCP — both connect through HTTP SSE.

### Explicit source section: 1. mcp-proxy sidecar architecture

**Decision: Add mcp-proxy sidecar container to Agent Home Pod**

Add mcp-proxy sidecar container to Agent Home Pod separately from existing sandbox container. The sidecar runs stdio MCP server as subprocess and converts it to HTTP SSE endpoint.

```
Agent Home Pod
├── sandbox container (existing)
│   ├── sandbox-daemon (:8081)
│   └── mitmproxy + socat
│
└── mcp-proxy sidecar container (new)
    ├── mcp-proxy (:9000)
    │   ├── /servers/ga4/sse → analytics-mcp subprocess
    │   └── /servers/{name}/sse → other stdio MCP servers
    ├── ConfigMap mount: /etc/mcp-proxy/config.json
    └── Secret mount: /var/run/secrets/mcp-creds/sa-key.json
```

**Details:**
- **Image**: image including mcp-proxy + Python/Node.js (for running stdio server)
- **Port**: 9000 (HTTP SSE/Streamable HTTP)
- **Resources**: requests 100m/128Mi, limits 500m/512Mi
- **ConfigMap**: `mcp-proxy-config-{agent_id}` — mcp-proxy named server config JSON
- **Secret**: `mcp-stdio-creds-{agent_id}` — credential files such as SA Key
- **readiness**: check mcp-proxy `/status` endpoint
- **lifecycle**: same as sandbox container (together on Pod create/delete)

**Docker environment (local development):**

Docker has no sidecar container concept, so run mcp-proxy inside sandbox container as supervisord subprocess.

```
Docker Container (sandbox)
├── supervisord
│   ├── sandbox-daemon
│   ├── mitmproxy + socat
│   └── mcp-proxy (:9000)  ← subprocess managed by supervisord
│       └── analytics-mcp subprocess
├── /etc/mcp-proxy/config.json  ← bind mount
└── SA Key  ← environment variable or bind mount
```

- Add `[program:mcp-proxy]` to supervisord config.
- Enable/disable with `ENABLE_MCP_PROXY` environment variable.
- Generate config.json on host and bind mount.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
