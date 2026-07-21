---
title: "Remove Dormant stdio MCP Sidecar Historical Requirements Reconstruction"
created: 2026-05-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: drop-260512
historical_reconstruction: true
migration_source: "docs/azents/adr/0029-drop-dormant-stdio-mcp-sidecar.md"
---

# Remove Dormant stdio MCP Sidecar Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `drop-260512`
- Source: `docs/azents/adr/drop-260512-drop-dormant-stdio-mcp-sidecar.md`
- Historical source date basis: `2026-05-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

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
