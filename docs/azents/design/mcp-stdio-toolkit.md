---
title: "MCP stdio Toolkit Design — Agent Home sidecar"
tags: [architecture, engine, infra]
created: 2026-03-25
updated: 2026-03-25
implemented: 2026-03-25
---

# MCP stdio Toolkit Design

> Prerequisite: [Sandbox Daemon Design](sandbox-daemon.md) (supervisord, Agent Home Pod management)

## Overview

Add mcp-proxy sidecar to Agent Home Pod so nointern agents can use stdio-based MCP servers (mcp-server-gcp, mcp-server-ga4, etc.).

**Problems solved:**
- Existing MCP toolkit is HTTP(SSE/Streamable HTTP)-based and cannot directly support stdio MCP servers.
- Convert stdio MCP servers to HTTP and reuse existing McpBasedToolkit code.

## Architecture

```
Worker Pod                               Agent Home Pod
┌──────────────────────────┐            ┌──────────────────────────────────┐
│ Engine                   │            │ sandbox container                │
│ ├─ McpBasedToolkit       │  HTTP SSE  │ ├─ supervisord                  │
│ │  (existing code)       │ ────────→  │ │  ├─ sandbox-daemon            │
│ │                        │ Pod IP     │ │  ├─ mitmproxy + socat         │
│ │                        │ :9000      │ │  └─ mcp-proxy (Docker only)  │
│ └─ resolve flow          │            │ └──────────────────────────────┘ │
│    ├─ detect stdio       │            │                                  │
│    ├─ Pod ensure_ready   │            │ mcp-proxy sidecar (K8s only)    │
│    └─ create server_url  │            │ └─ :9000                        │
└──────────────────────────┘            │    ├─ /servers/{name}/sse       │
                                        │    └─ manage stdio subprocess   │
                                        └──────────────────────────────────┘
```

### mcp-proxy placement by environment

| Environment | mcp-proxy location | Reason |
|---|---|---|
| K8s | sidecar container | separate container inside Pod, standard K8s pattern |
| Docker | subprocess inside sandbox container | Docker has no sidecar concept, managed by supervisord |

## Toolkit Design

### Internal implementation, not user-facing

`mcp_stdio` is not a separate `ToolkitType`. Like GitHub and Notion, each service-specific ToolkitProvider internally chooses stdio/HTTP transport depending on integration method.

```
User-facing                         Internal implementation
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

Do not add `MCP_STDIO` to `ToolkitType` enum.

### McpStdioToolkitConfig

```python
@dataclasses.dataclass(frozen=True)
class McpStdioToolkitConfig:
    name: str                    # server identifier name (mcp-proxy named server name)
    command: str                 # command (e.g. "uvx", "npx")
    args: list[str] = ()        # command args (e.g. ["mcp-server-gcp", "--project", "my-project"])
    env: dict[str, str] = ()    # non-sensitive settings
    timeout: float = 30.0
```

Separate command/args — matches mcp-proxy `--named-server-config` JSON format:

```json
{
  "mcpServers": {
    "gcp": {
      "command": "uvx",
      "args": ["mcp-server-gcp"],
      "env": {"PROJECT_ID": "my-project"}
    }
  }
}
```

## mcp-proxy

### Role

Run stdio MCP server as subprocess and expose HTTP SSE endpoint.

- Python package: [mcp-proxy](https://pypi.org/project/mcp-proxy/)
- Pass JSON config file with `--named-server-config` option
- Expose each server as `/servers/{name}/sse` (SSE) or `/servers/{name}/mcp` (Streamable HTTP)
- Check overall server status with `/status`

### Image

Image includes Python + Node.js and installs mcp-proxy. stdio MCP servers are not pre-installed and run at runtime through `uvx`, `npx`.

If cold start optimization is needed later, improve by pre-installing frequently used servers.

### Credential Delivery

Inject with K8s Secret:

1. Decrypt agent's stdio toolkit credential from DB on Pod creation.
2. Create `mcp-stdio-creds-{agent_id}` Secret.
3. Inject into sidecar container with `envFrom: secretRef`.
4. Prevent plaintext credential exposure in Pod spec.

Non-sensitive settings (command, args, env) are injected directly into Pod spec.

## Resolve Flow

```
1. Start resolve_agent_tools()
2. Collect stdio configs from agent toolkit list
3. Any stdio toolkit?
   ├─ YES: Agent Home Pod ensure_ready (eager creation)
   │       Build sidecar config with latest toolkit list on Pod creation
   │       Worker sends "Starting..." to interface
   └─ NO:  keep existing lazy creation
4. Check Pod IP
5. Auto-generate server_url for each stdio toolkit:
   http://{pod_ip}:9000/servers/{name}/sse
6. Connect with existing McpBasedToolkit over HTTP (reuse code)
```

From Engine perspective, stdio MCP and HTTP MCP are the same — both connect via HTTP SSE.

## Pod Spec Application

### Timing

Applied on next session start. Not applied immediately when toolkit is registered/changed. After existing Pod goes down by idle timeout, next session creates new Pod with latest config. If immediate application is needed, use admin restart interface.

### K8s Pod Spec Changes

Add conditional sidecar container to existing `_build_pod_spec()`:

```python
containers = [sandbox_container]

if stdio_configs:
    mcp_proxy_container = V1Container(
        name="mcp-proxy",
        image=config.mcp_proxy_image,
        args=["--named-server-config", "/etc/mcp-proxy/config.json", "--port", "9000"],
        ports=[V1ContainerPort(container_port=9000)],
        volume_mounts=[
            V1VolumeMount(name="mcp-config", mount_path="/etc/mcp-proxy"),
            V1VolumeMount(name="mcp-creds", mount_path="/var/run/secrets/mcp-creds"),
        ],
        env_from=[V1EnvFromSource(secret_ref=V1SecretEnvSource(name=f"mcp-stdio-creds-{agent_id}"))],
    )
    containers.append(mcp_proxy_container)

    volumes += [
        V1Volume(name="mcp-config", config_map=V1ConfigMapVolumeSource(name=f"mcp-proxy-config-{agent_id}")),
        V1Volume(name="mcp-creds", secret=V1SecretVolumeSource(secret_name=f"mcp-stdio-creds-{agent_id}")),
    ]
```

Mount mcp-proxy JSON config through ConfigMap.

### Docker (local development)

In Docker, run mcp-proxy as subprocess inside sandbox container instead of sidecar. Add to supervisord config:

```ini
[program:mcp-proxy]
command=mcp-proxy --named-server-config /etc/mcp-proxy/config.json --port 9000
autostart=%(ENV_ENABLE_MCP_PROXY)s
autorestart=true
```

config.json is generated on host and bind mounted into container.

## Network Security

No existing NetworkPolicy change.

- **Egress**: keep existing private IP blocking in sandbox namespace. External API calls from stdio MCP server are public IPs, so already allowed. egress proxy not needed (NetworkPolicy prevents SSRF).
- **Ingress**: same as Sandbox daemon — add Ingress NetworkPolicy allowing only Worker Pod.

## Agent Home Pod Management Interface

For cases requiring Agent Home Pod recreation such as stdio toolkit config change:

- **Admin restart**: interface allowing admin to restart specific agent's Agent Home Pod at desired time (Admin API, etc.)
- **Automatic restart policy**: define conditions requiring system restart (toolkit config change, image update, etc.) and timing policy

## Implementation Plan

> Proceed after Sandbox Daemon (Phase 1-3) completes

### Phase 1: mcp-proxy sidecar (K8s)

1. Build mcp-proxy image (Python + Node.js + mcp-proxy)
2. Add `McpStdioToolkitConfig`
3. Add conditional sidecar to `K8sAgentHomeClient._build_pod_spec()`
4. ConfigMap/Secret creation logic
5. Detect stdio in resolve flow + eager pod creation

### Phase 2: Provider Integration

1. stdio/HTTP transport selection logic in service-specific ToolkitProvider
2. Auto-generate `server_url` (`http://{pod_ip}:9000/servers/{name}/sse`)
3. Verify connection with existing McpBasedToolkit

### Phase 3: Docker Support + Verification

1. Add mcp-proxy to supervisord config (Docker environment)
2. Docker local development E2E verification
3. K8s environment E2E verification

## Alternatives Considered

### 1. Separate mcp-bridge Pod

Run stdio MCP-only Pod per agent and convert to HTTP with mcp-proxy.

- Rejected: Pod management complexity, additional network hop, image packaging problem

### 2. Move Engine into Agent Home Pod

Place Engine container + sandbox container in same Pod. Isolate secrets with container boundary.

- Rejected: NetworkPolicy is Pod-scoped, so opening DB/Redis access for engine also allows private IP access from sandbox. Principle is to never allow internal IP access from sandbox.
- Additional rejected variants:
  - Delegate DB/Redis to Worker via RPC: unrealistic because EventStore etc. are deeply tied into engine
  - Separate Engine and Sandbox into separate Pods + separate namespaces: returns to two Pods and original problem recurs

### 3. Put Engine in same container as sandbox

- Rejected: bwrap escape directly exposes engine secrets
