---
title: "stdio MCP Infrastructure + Google Analytics Toolkit Integration Design"
tags: [architecture, engine, infra, frontend, historical-reconstruction]
created: 2026-03-26
updated: 2026-03-26
implemented: 2026-03-26
document_role: primary
document_type: design
snapshot_id: stdio-260326
migration_source: "docs/azents/design/stdio-mcp-ga4-integration.md"
historical_reconstruction: true
---

# stdio MCP Infrastructure + Google Analytics Toolkit

> Base design: [MCP stdio toolkit design](mcp-260325-mcp-stdio-sidecar.md)
> Reference: [Google Analytics MCP](https://github.com/googleanalytics/google-analytics-mcp) (Google official, 7 tools)

## Overview

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

## Architecture

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

## Discussion Points and Decisions

### 1. mcp-proxy sidecar architecture

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

### 2. Credential delivery

**Decision: Mount SA Key JSON with K8s Secret**

1. Decrypt agent's stdio toolkit credential from DB on Pod creation.
2. Create `mcp-stdio-creds-{agent_id}` Secret (SA Key JSON file).
3. Volume mount into sidecar container.
4. Specify path with `GOOGLE_APPLICATION_CREDENTIALS` environment variable.

### 3. Pod creation timing

**Decision: eager Pod creation when stdio toolkit detected**

Existing: lazy creation on Shell execution (Pod created on first exec).
stdio: detect stdio toolkit in resolve_agent_tools() → immediately call ensure_ready.

Can deliver "Starting..." message to user (using Worker interface adapter).

### 4. GA4 MCP server

**Decision: `analytics-mcp` (Google official, PyPI)**

- 7 tools: run_report, run_realtime_report, get_account_summaries, etc.
- `pipx run analytics-mcp` or pre-install.
- SA Key → `GOOGLE_APPLICATION_CREDENTIALS`.
- Read-only (analytics.readonly scope).

### 5. UX: latency guidance

**Decision: Frontend gives prior notice that sandbox wait may happen**

stdio toolkit must wait for sandbox (Agent Home Pod) startup. First session start can wait ~30 seconds. UI says:
- "This tool requires sandbox startup. First use may wait up to 30 seconds."
- Later sessions can use immediately while Pod remains alive (until idle timeout).

## Changed Files

### Infrastructure (stdio MCP base)

| File | Change |
|------|------|
| `core/config.py` | add `k8s_mcp_proxy_image` setting |
| `runtime/sandbox/agent_home.py` | add stdio config to `ensure_ready()` signature |
| `runtime/sandbox/agent_home_k8s.py` | add sidecar container + ConfigMap/Secret to `_build_pod_spec()` |
| `runtime/sandbox/agent_home_factory.py` | pass mcp_proxy_image config |
| `runtime/sandbox/agent_home_manager.py` | pass stdio config |

### GA4 Toolkit

| File | Change |
|------|------|
| `core/tools.py` | `ToolkitType.GOOGLE_ANALYTICS` + `GoogleAnalyticsToolkitConfig` |
| `engine/tools/google_analytics.py` | Provider + Toolkit (stdio connection) |
| `engine/tools/deps.py` | registry registration |
| `GoogleAnalyticsConfigFields.tsx` | Frontend component |
| `ToolkitForm.tsx` | google_analytics branch |

## Implementation Plan

### Phase 1: McpStdioToolkitConfig + Config

- Define `McpStdioToolkitConfig` dataclass.
- Add `k8s_mcp_proxy_image` to `core/config.py`.
- Pass config from `agent_home_factory.py`.

### Phase 2: K8s Pod Spec — add sidecar

- `agent_home.py`: add `stdio_configs` to `ensure_ready()` signature.
- `agent_home_k8s.py`:
  - conditionally add sidecar container to `_build_pod_spec()`.
  - create ConfigMap (mcp-proxy named server config).
  - create Secret (SA Key JSON).
  - volume mounts.

### Phase 3: GA4 Backend — Provider

- `ToolkitType.GOOGLE_ANALYTICS` + `GoogleAnalyticsToolkitConfig`.
- `GoogleAnalyticsToolkitProvider`:
  - `resolve()`: create McpStdioToolkitConfig, wait for sandbox.
  - `create_tools()`: connect to mcp-proxy sidecar HTTP → tools/list → wrap.
- Register in registry.

### Phase 4: GA4 Frontend

- `GoogleAnalyticsConfigFields.tsx`
- Integrate `ToolkitForm.tsx`
- Sandbox wait time guidance UI

## GA4 Provided Tools (7)

| Tool | API | Description |
|------|-----|------|
| `get_account_summaries` | Admin API | account/property list |
| `get_property_details` | Admin API | property details |
| `list_google_ads_links` | Admin API | Ads links |
| `list_property_annotations` | Admin API | property annotations |
| `get_custom_dimensions_and_metrics` | Data API | custom dimensions/metrics |
| `run_report` | Data API | standard report |
| `run_realtime_report` | Data API | realtime report |

## Feasibility

| Item | Status | Note |
|------|------|------|
| mcp-proxy PyPI package | ✅ | `mcp-proxy` (stdio→HTTP conversion) |
| analytics-mcp PyPI package | ✅ | Google official, 7 tools |
| K8s sidecar container | ✅ | standard pattern, extend existing Pod spec |
| ConfigMap/Secret creation | ✅ | use existing K8s client |
| Reuse McpBasedToolkit | ✅ | sidecar converts to HTTP |
| SA Key auth | ✅ | GOOGLE_APPLICATION_CREDENTIALS |

## Risks

| Risk | Mitigation |
|--------|------|
| Cold start (~30 seconds) | eager creation + UI guidance |
| mcp-proxy compatibility | pin version, dynamic tools/list discovery |
| Sidecar resources | set resource limits (200m CPU, 256Mi) |
