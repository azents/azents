---
title: "Remove Dormant stdio MCP Sidecar"
created: 2026-05-12
tags: [architecture, engine, infra, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: drop-260512
historical_reconstruction: true
migration_source: "docs/azents/adr/0029-drop-dormant-stdio-mcp-sidecar.md"
---

# drop-260512/ADR: Remove Dormant stdio MCP Sidecar

> 📌 **Related design document**: [drop-260512-drop-dormant-stdio-mcp-sidecar.md](../design/drop-260512-drop-dormant-stdio-mcp-sidecar.md)

## Context

nointern previously added a path that placed a per-agent `mcp-proxy` sidecar next to Agent Home to support stdio-only MCP servers.

The core path included:

- `McpStdioToolkitConfig`, `Toolkit.get_stdio_configs()`, and `Toolkit.set_server_url()` in `core/tools.py`.
- `EngineWorker.initialize_stdio_sandbox()` in `worker/engine.py`.
- `mcp-proxy` sidecar Pod spec, ConfigMap/Secret creation, and Pod reuse compatibility checks in `runtime/sandbox/session_sandbox_k8s.py`.
- `ENABLE_MCP_PROXY`, bind mounts, and local subprocess path in `runtime/sandbox/session_sandbox_docker.py`.

However, in the current code:

1. `Toolkit.get_stdio_configs()` has only the default implementation and no override.
2. `Toolkit.set_server_url()` has only the default no-op implementation and no override.
3. There are no real `McpStdioToolkitConfig(...)` instances in use.
4. Actual toolkits use remote HTTP/Streamable HTTP MCP or native SDK paths.

In other words, sidecar wiring remains, but it is close to a **dormant feature branch that no current toolkit produces**.

Meanwhile, this path spreads across runtime, sandbox, infra, CI, testenv, and spec, continuously increasing operational complexity and change cost.

## Decision

Remove the per-agent stdio MCP sidecar path.

Specifically:

1. **Reduce current support contract**
   - nointern runtime no longer supports per-agent stdio MCP transport.
   - Supported paths are reduced to:
     - remote HTTP / Streamable HTTP MCP
     - service-specific native integrations

2. **Simplify runtime**
   - Remove `McpStdioToolkitConfig`, `get_stdio_configs()`, `set_server_url()`, and `initialize_stdio_sandbox()`.
   - Remove `mcp-proxy sidecar presence` from sandbox allocation/reuse judgment.

3. **Simplify sandbox / infra**
   - Remove `mcp-proxy` sidecar from K8s Pod spec, plus related ConfigMap/Secret, RBAC, NetworkPolicy, and image settings.
   - Remove Docker local dev `ENABLE_MCP_PROXY`, supervisord `mcp-proxy` subprocess, and related bind mounts.

4. **Clean up documentation contract**
   - Preserve historical document [mcp-260325/ADR](./mcp-260325-mcp-stdio-sidecar.md) unchanged.
   - Record the current decision in this ADR and the new design document.
   - Update living spec to match current behavior in the implementation PR.

## Consequences

### Positive

- Reduces dormant code and operational surface area.
- Simplifies sandbox reuse conditions.
- Removes management cost for `nointern-mcp-proxy` image/deployment/permissions/tests.
- Removes the independent failure axis of stdio-sidecar failure.

### Negative

- Removes the path for attaching stdio-only MCP servers.
- If stdio-only MCP becomes necessary later, a separate bridge or native integration must be designed again.

### Migration

- The design document PR does not touch implementation/spec.
- Actual implementation should proceed in this order: remove runtime → recycle sandbox → clean up infra/CI/testenv → update spec.

## Alternatives

### 1. Keep current state

- Pros: can immediately support future stdio-only MCP needs.
- Cons: keeps unused complexity.
- Reason rejected: evidence shows the path is dormant, and long-term preservation has low value.

### 2. Remove only K8s sidecar and keep Docker subprocess

- Pros: leaves room for local experiments.
- Cons: most abstraction and test surface remains.
- Reason rejected: the core problem is dormant transport itself. Keeping environment-specific branches provides little complexity reduction.

### 3. Replace per-agent sidecar with central bridge service

- Pros: could centralize future stdio support.
- Cons: adds a new operational component without current need.
- Reason rejected: what is needed now is removal of the dormant path, not a replacement implementation.

## Migration provenance

- Historical source filename: `0029-drop-dormant-stdio-mcp-sidecar.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
