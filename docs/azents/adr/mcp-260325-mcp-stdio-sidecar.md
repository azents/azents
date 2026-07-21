---
title: "Agent Home Sidecar Discussion (MCP stdio + File ops)"
created: 2026-03-25
tags: [architecture, engine, infra, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: mcp-260325
historical_reconstruction: true
migration_source: "docs/azents/adr/0018-mcp-stdio-sidecar.md"
---

# mcp-260325/ADR: Agent Home Sidecar Design

> 📌 **Related**: [mcp-260325-mcp-stdio-sidecar.md](../design/mcp-260325-mcp-stdio-sidecar.md)

> Status: discussion completed and split into design documents.
>
> - [Sandbox Daemon design](../design/sandbox-daemon.md) — Shell + File tool integration, first implementation
> - [MCP stdio toolkit design](../design/mcp-260325-mcp-stdio-sidecar.md) — stdio MCP sidecar, second implementation
>
> This document is preserved as a discussion record.

## Background

This design improves stdio MCP support and file management for nointern agents. During the discussion, we reviewed expanding the role of the Agent Home Pod and considered several architecture alternatives.

## Confirmed Architecture

Keep the Engine in the Worker Pod and add sidecars to the Agent Home Pod.

```text
Worker Pod (minimal changes)              Agent Home Pod (nointern-sandbox)
┌──────────────────────────┐            ┌──────────────────────────────────┐
│ Engine (unchanged)       │            │ sandbox container (existing)      │
│ ├─ ReAct loop            │            │ └─ Shell (bwrap-exec)            │
│ ├─ LLM, DB, Redis        │  K8s exec  │                                  │
│ ├─ all secrets           │ ─────────→ │ file tools also go through        │
│ ├─ MCP HTTP              │            │ bwrap-exec                       │
│ ├─ Adapters              │  HTTP SSE  │ mcp-stdio sidecar (new)          │
│ └─ Agent Home state mgmt │ ─────────→ │ └─ mcp-proxy: stdio→HTTP bridge  │
│                          │  Pod IP    │                                  │
└──────────────────────────┘            │ Shared: /mnt/agent-data (EFS)    │
                                        └──────────────────────────────────┘
```

### Work Split

Proceed as two independent work items:

**Work A: MCP stdio sidecar**

- Add an mcp-proxy sidecar container to the Agent Home Pod.
- Add stdio/HTTP transport selection logic in each service-specific ToolkitProvider.
- Add `McpStdioToolkitConfig`, resolve flow, and Pod spec generation.

**Work B: Move File tools + Shell to sandbox daemon**

- Run a lightweight HTTP daemon inside the sandbox container.
- Remove the existing File-API as the path for LLM-facing file operations.
- Move Shell execution through the daemon as well, removing K8s exec dependency.
- Expand file access to the whole sandbox filesystem.

The two work items can proceed in parallel without dependencies. However, once the sandbox daemon from Work B is complete, Shell should also move from K8s exec to the daemon path.

### Why the Worker Keeps the Interface

Agent Home Pods are created lazily and have cold start latency of around 10 seconds. During that time, the system must still communicate with users, such as sending "starting..." to Slack. Therefore, interface adapters must remain in the always-running Worker.

### RPC Protocol Between Worker and Engine, Bidirectional

The Engine stays in the Worker for now, but the interface is clarified for possible future separation.

| Direction | Method | Purpose |
|---|---|---|
| Worker → Engine | `StartRun(config, initial_events)` | Start session |
| Worker → Engine | `StopRun()` | Stop request |
| Engine → Worker | `StreamEvent(Emit)` | Stream events such as text and tool calls |
| Engine → Worker | `PullMessages() → [events]` | Fetch queued messages between turns |

**Why PullMessages is needed:**

- New messages can arrive in the middle of the ReAct loop.
- Message ownership should remain in the Worker to avoid loss if the Engine crashes.
- Between turns, the Engine asks the Worker to pull messages; the Worker removes them from its queue and passes them along.

---

## Alternatives Reviewed

### 1. mcp-bridge Pod, separate Pod

Run a dedicated Pod per agent for stdio MCP and convert stdio to HTTP through mcp-proxy.

- Reason rejected: Pod management complexity, extra network hop, and image packaging problems.

### 2. Move Engine into Agent Home Pod as a separate container

Place an Engine container and sandbox container in the same Pod. Isolate secrets by container boundary.

- Pros: direct file operations, shell localhost communication, direct stdio MCP subprocess.
- **Reason rejected: NetworkPolicy is Pod-scoped. If DB/Redis access is opened for the Engine, the sandbox also gains access to private IPs. Our principle is to never allow internal IP access from the sandbox in any form.**

Additional rejected variants from the review:

- Engine delegates DB/Redis to Worker through RPC: unrealistic because EventStore, OAuth token refresh, and related concerns are deeply embedded inside the Engine.
- Engine keeps only LLM keys and delegates DB to Worker: rejected for the same reason.
- Engine and Sandbox as separate Pods + separate namespace: two Pods reintroduce the original problems of network hops and File-API need.

### 3. Put Engine in the same container as the sandbox

- Reason rejected: if bwrap is escaped, engine secrets are directly exposed.

---

## Communication Method by Component

### Sandbox Daemon — HTTP server inside sandbox container

To solve production problems with K8s exec, such as K8s API load, rate limits, and WebSocket resource usage, run a lightweight HTTP daemon inside the sandbox container.

```text
Engine (Worker Pod) → http://{pod_ip}:{port}/... → sandbox daemon
```

- Shell execution and File operations both go through this daemon.
- Removes K8s API dependency.
- Binary and large files can be handled through HTTP streaming, such as multi-MB images.

**Security:**

- The daemon binds to 0.0.0.0 because the Worker Pod must access it by Pod IP.
- User code inside bwrap cannot access localhost because of network namespace separation through `--unshare-net`.
- Access from other Pods in the cluster is limited to Worker only through Ingress NetworkPolicy.
- mTLS is unnecessary because NetworkPolicy is sufficient.
- Per-user isolation is handled by the daemon at application level.

**Daemon capabilities:**

#### Shell execution

```text
POST /exec
```

- daemon runs commands through bwrap-exec.
- stdin/stdout streaming.

#### File tools, full sandbox filesystem access

```text
GET  /files/{path}     # read
PUT  /files/{path}     # write
PATCH /files/{path}    # edit; exact match replacement handled by daemon
DELETE /files/{path}   # delete
GET  /files/glob       # pattern search (find)
GET  /files/grep       # regex search (grep -rn)
```

- Can access all files available inside the sandbox, through the bwrap namespace.
- Includes system files such as `/usr/bin/` and `/etc/` as read-only.
- Exposed to the LLM as tool versions of cat, tee, sed, and similar operations.
- Special characters and encoding are handled by tool implementation, such as base64.

**File-API remains.** It continues to be used for:

- Reading Memory/Skills at tool resolution time, which must work without an Agent Home Pod.
- Serving platform skills under `/data/platform/`, baked into the sandbox image.
- Attachment upload/download from API Server.
- Session data management.
- Image storage and output truncation through SessionDataSaver.

Reason to keep File-API: memory/skills loading and attachment handling must work even when there is no Agent Home Pod. The sandbox daemon is only for LLM-facing file tools that need full filesystem access.

### MCP stdio — mcp-proxy sidecar (HTTP SSE)

```text
Engine → http://{pod_ip}:9000/servers/{name}/sse → mcp-proxy sidecar → stdio subprocess
```

- mcp-proxy converts stdio to SSE.
- From the Engine perspective, existing MCP HTTP toolkit code is reused as-is.
- Only `server_url` is set based on Pod IP.

### MCP HTTP — unchanged

```text
Engine → (egress proxy) → external MCP server
```

- No change.

---

## Open Discussion Items

### ~~Discussion 4: toolkit_type distinction~~ — decided

`mcp_stdio` is not a user-facing toolkit_type. It is an internal implementation detail.

Service-specific ToolkitProviders, such as GitHub and Notion, choose stdio/HTTP transport internally based on integration method. Users do not need to know about MCP.

```text
User-facing view                    Internal implementation
┌──────────────┐
│ Notion       │
│ ├─ API link  │ ──→ McpStdioToolkitConfig (sidecar)
│ └─ OAuth link│ ──→ McpToolkitConfig (HTTP)
├──────────────┤
│ GCP          │
│ └─ API link  │ ──→ McpStdioToolkitConfig (sidecar)
├──────────────┤
│ Custom MCP   │
│ └─ URL input │ ──→ McpToolkitConfig (HTTP)
└──────────────┘
```

Do not add `MCP_STDIO` to the `ToolkitType` enum. The provider decides transport inside existing service-specific types such as `NOTION` and `GCP`.

**McpStdioToolkitConfig**, internal use:

```python
class McpStdioToolkitConfig:
    name: str                    # server identifier; mcp-proxy named server name
    command: str                 # command to run, such as "uvx" or "npx"
    args: list[str] = []         # command args, such as ["mcp-server-gcp", "--project", "my-project"]
    env: dict[str, str] = {}     # non-sensitive config values
    timeout: float = 30.0
```

Matches mcp-proxy `--named-server-config` JSON shape with command/args split:

```json
{
  "mcpServers": {
    "{name}": {
      "command": "{command}",
      "args": ["{args}"],
      "env": {"{env}"}
    }
  }
}
```

**Resolve flow:**

1. Collect the agent's stdio toolkit list at resolve time.
2. Ensure Agent Home Pod is ready; when creating the Pod, build sidecar config from the latest toolkit list.
3. Automatically create Pod-IP-based server_url: `http://{pod_ip}:9000/servers/{name}/sse`.
4. Connect using existing `McpBasedToolkit` over HTTP.

**Pod spec reflection timing:** next session start.

Toolkit registration/changes are not applied immediately. After the existing Pod goes down by idle timeout, the next session creates a new Pod with the latest config. If immediate reflection is needed, use the admin restart interface from Discussion 4.1.

### Discussion 4.1: Agent Home Pod management interface

For cases where Agent Home Pod recreation is needed, such as stdio toolkit config changes:

- **Admin restart**: an interface, such as Admin API, that lets an administrator restart a specific agent's Agent Home Pod at a chosen time.
- **Automatic restart policy**: define conditions requiring restart, such as toolkit config changes or image updates, and timing policy, such as immediate, on idle, or next session start.

### ~~Discussion 5: Network security~~ — resolved

**Egress**: keep the existing NetworkPolicy.

- Engine is in Worker, so DB/Redis access stays on the Worker side.
- Agent Home keeps existing private IP blocks.
- mcp-stdio sidecar egress: public IP is already allowed and private IP is already blocked, preventing SSRF.
  - Worker uses egress proxy for HTTP MCP to prevent SSRF, but the sandbox namespace already blocks private IP through NetworkPolicy, so no proxy is needed.

**Ingress**: add Ingress NetworkPolicy because sandbox daemon and mcp-stdio sidecar open ports.

- Only Worker Pods can access Agent Home ports.
- User code inside bwrap cannot access localhost because of `--unshare-net` network namespace separation.
- mTLS is unnecessary because NetworkPolicy is sufficient.

### ~~Discussion 6: Image strategy~~ — decided

- sandbox container: keep existing nointern-agent-runtime image.
- mcp-stdio sidecar: image including Python + Node.js.
  - Install mcp-proxy.
  - Do not preinstall stdio MCP servers; run them at runtime with `uvx` and `npx`.
  - Keep the image light and avoid image rebuilds for new servers.
  - If cold start optimization is later needed, preinstall frequently used servers.

### ~~Discussion 7: File tool encoding safety~~ — resolved

Handled in tool implementation, such as base64 stdin. The LLM does not write shell commands directly; tools like `write_file(path, content)` generate safe commands internally. This is not an architecture discussion item.

### Discussion 8: File tool migration details — decided

**Decision: sandbox daemon, an in-container HTTP server, plus keeping File-API**

Use an HTTP daemon inside the sandbox container instead of K8s exec.

- K8s exec is designed for debugging/administration and is unsuitable as a production communication channel because of API server load, rate limits, and WebSocket resource usage.
- The daemon handles shell + LLM-facing file tools.
- File-API remains for infrastructure file operations: memory, skills, attachments, and session data.

**Responsibility split:**

| Role | Owner | Reason |
|---|---|---|
| LLM-facing file tools, such as read_text, write, edit | sandbox daemon | Needs full filesystem access |
| Shell execution | sandbox daemon | Removes K8s exec dependency |
| Memory/Skills reading | File-API | Must work without Pod |
| Platform skills | File-API | Baked into sandbox image; Worker cannot access directly |
| Attachment upload/download | File-API | Used by API Server |
| Image storage, output truncation | File-API | SessionDataSaver inside engine |

**LLM-facing tool migration:**

| Current Tool | Change | Notes |
|---|---|---|
| read_text | daemon GET → bwrap-exec cat | supports offset/limit |
| read_image | daemon GET → returns base64 | handles multi-MB images with HTTP streaming |
| write | daemon PUT | passes base64 through stdin |
| edit | daemon PATCH, replacement handled by daemon | exact match, replace_all |
| delete_file | daemon DELETE | |
| glob | daemon → bwrap-exec find | improves current N+1 calls to one call |
| grep | daemon → bwrap-exec grep -rn | greatly improves current N+1 calls to one call |
| present_file | daemon GET + thumbnail generation | PIL handled by daemon |
| Shell execution | daemon POST /exec → bwrap-exec | removes K8s exec dependency |

**Path security model**: bwrap mount namespace based.

The sandbox can access all files it has permission for, including system files. This is intended behavior. `/data/platform/` is already mounted through bwrap as `--ro-bind /opt/platform-data /data/platform`.

### Discussion 9: Cold Start Lifecycle — decided

**Basic conversation must be possible even when no Pod exists.**

Current FileApiClient usage points:

- Phase 1, tool resolution: read memory and skills → File-API, always available
- Phase 2, tool execution: file tools and shell → sandbox daemon, requires Pod

Because File-API remains, Phase 1 works without a Pod and existing behavior is preserved.

**Pod creation timing:**

| Agent Type | Pod Creation Timing | Reason |
|---|---|---|
| Has stdio toolkit | Immediately during resolve, eager | `list_tools()` needs sidecar access |
| No stdio toolkit | On first tool execution, lazy | Same as current pattern |

The branch is simple. Eager/lazy is determined by whether the agent's toolkit list includes stdio.

### Discussion 10: Sandbox Container Process Management — decided

**Introduce supervisord.**

The sandbox container needs to manage three processes:

1. mitmproxy, existing
2. socat, existing
3. sandbox daemon, new

The current bash background process style cannot detect process death, propagate SIGTERM, or provide health checks. Move to supervisord for process lifecycle management.

`entrypoint.sh` runs supervisord, and supervisord manages every process:

```text
entrypoint.sh → supervisord
  ├─ mitmproxy
  ├─ socat
  └─ sandbox-daemon
```

### Discussion 11: Implementation Details — decided

**Docker local development:**

- mcp-proxy sidecar: Docker has no sidecar concept, so run it inside the sandbox container as a subprocess managed by supervisord. In Kubernetes, run it as a sidecar container.
- sandbox daemon: run inside the sandbox container in both Kubernetes and Docker.

**File tool path:**

- LLM-facing file tools always go through sandbox daemon. Pod is required.
- If no Pod exists, lazily create it and then execute, same as shell.
- No File-API fallback. No dual path.

**Shell streaming:**

- Chunked HTTP through FastAPI `StreamingResponse`.
- stdin is unnecessary because bwrap-exec runs `bash -c "$@"`.
- Minimal overhead; binary-safe.

**Daemon code location:**

- `python/apps/nointern-sandbox-daemon/` — separate app.
- Same pattern as File-API (`nointern-file-api`).

---

## Previous Decisions, Based on mcp-bridge and Replaced by the Current Architecture

> The content below predates the current architecture decision. It is preserved as a reference for baseline stdio MCP requirements.

### Bridge Tool: mcp-proxy (Python)

- Supports named server multiplexing: one process manages multiple stdio MCP servers.
- Exposes each server through `/servers/{name}/sse`.
- supergateway was rejected due to memory leak issues.

### Credential Delivery: K8s Secret

- Create `mcp-stdio-creds-{agent_id}` Secret.
- Inject through `envFrom: secretRef`.
- Avoid exposing credential plaintext in Pod spec.

### Server List: Direct env Injection

- command/args are not sensitive, so inject directly as Pod spec env.
- `MCP_SERVERS_CONFIG='{"gcp": {"command": "mcp-gcp"}, "ga4": {"command": "mcp-ga4"}}'`

## Migration provenance

- Historical source filename: `0018-mcp-stdio-sidecar.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
