---
title: "ADR-0008: Adopt AgentRuntime-Based Sandbox Control Channel"
created: 2026-05-06
tags: [architecture, backend, engine, infra, security]
---

# ADR-0008: Adopt AgentRuntime-Based Sandbox Control Channel

## Context

The current NoIntern sandbox control path has the nointern worker/API discover a Kubernetes Pod IP or Docker container network address, then call the `sandbox-daemon` sidecar HTTP API inbound. This was useful as an intermediate step for isolating helper processes from custom/root sandbox containers, but it does not fit the default product sandbox model.

The current model has these major limitations:

1. Sandbox discovery and control are tightly coupled to Kubernetes Pod IPs, sidecar HTTP ports, and daemon readiness.
2. The name and public API of `SessionSandboxManager` imply session-bound ownership. In reality, the sandbox lifecycle owner is `AgentRuntime`, not `AgentSession`.
3. File read/write is based on whole-body request/response, making large file streaming, backpressure, and resume difficult to express.
4. External sandbox vendors, local-machine sandboxes, and controlled sandbox images should have the sandbox client register outbound instead of having nointern connect inbound.
5. Delivering commands through Kubernetes exec inside the same Pod unnecessarily binds the command/file control plane to the Kubernetes API.

Issue #3426 and Discussion #3445 decided on the following direction.

## Decision

Adopt the following principles:

1. The sandbox lifecycle owner is `AgentRuntime`. `AgentSession` is used only as a permission, UI, and event boundary.
2. Treat the session-bound API of `SessionSandboxManager` as a design error and correct it to a runtime-centric API.
3. The sandbox client runs inside the sandbox and opens an outbound control channel to nointern.
4. The control channel protocol uses gRPC bidirectional streaming.
5. The primary key for the connection registry is `AgentRuntime.id`. Each stream also has its own `connection_id` and `generation`.
6. Command and file protocols are streaming-first. Existing tool and workspace browser call sites remain behind facades during migration, but the internal transport moves to gRPC streams.
7. File transfer is supported from v1. The initial protocol includes chunk/offset/backpressure/cancel/error contracts.
8. Outbound client becomes the only primary mode. The existing sidecar/server-discovered daemon path is a migration target and will not remain a long-term primary mode.
9. The worker Pod and sandbox stream owner Pod may differ, so worker-to-owner request routing is a required prerequisite before daemon removal.
10. The control stream separates registry and request routing to account for worker/API replica failure and reconnect.
11. Worker-to-stream-owner routing uses a dedicated sandbox management/control service topology. Workers send only command/file requests across the service boundary, and the service is responsible for sandbox lifecycle ensure, connection readiness wait, owner registry lookup, and replica routing.
12. The router is route-only. New sandbox start/resume is handled by the lifecycle manager inside the service.
13. Worker request ID and gRPC `request_id` are the same value.

## Consequences

### Positive

- Sandbox ownership is fixed to AgentRuntime, so reset/new AgentSession behavior no longer mixes with sandbox lifecycle.
- Kubernetes Pod IP inbound dependency and sandbox daemon ingress NetworkPolicy can be removed.
- External vendors and local-machine sandboxes can use the same outbound registration protocol.
- Command stdout/stderr, file read/write, cancel, and heartbeat can be defined in one typed protocol.
- Large file transfer can reduce memory amplification and explicitly express backpressure.

### Negative

- Python gRPC/protobuf dependencies and codegen workflow are added.
- Lifecycle orchestration and stream-owner replica routing must be implemented inside the dedicated sandbox management/control service.
- HTTP/2 gRPC paths are added to ALB/Service/NetworkPolicy.
- Naming/API refactors must happen first for `SessionSandboxManager`, `SessionSandboxClient`, workspace browser, and shell/file tool call sites.
- Moving to outbound-only requires multiple migration PRs because it also removes the existing daemon path.

## Alternatives

### WebSocket + JSON/binary frame protocol

Rejected. It could reuse existing FastAPI WebSocket experience, but the team can accept gRPC operational cost, and managing command/file streaming schemas as typed contracts is better long-term.

### HTTP long polling + signed request

Rejected. Simpler to implement, but not expressive enough for stdout/stderr streaming, cancel, large file transfer, and backpressure.

### Keep existing sidecar daemon mode as primary

Rejected. The high-isolation sidecar is treated as an intermediate implementation. The primary product path should be unified around outbound sandbox clients.

### Redis/Valkey direct request routing

Rejected. Redis can be used for registry/TTL, but workers should not write command/file requests directly to Redis. Routing responsibility between worker and stream owner belongs behind the dedicated sandbox-control service boundary.

### AgentSession-based sandbox registry

Rejected. AgentSession is a conversation/event boundary and can rotate on reset/new. Sandbox filesystem and control channel lifecycle must belong to AgentRuntime.

### Routing using only process-local store in the control service

Rejected. nointern workers and nointern-server/control endpoints run in separate Pods, so a worker cannot directly see the stream owner's process-local store. Process-local store is used only for live stream dispatch owned by that replica; worker requests must be forwarded to the owner replica through a separate routing design.

## Status

Accepted. The detailed design follows `docs/nointern/design/in-sandbox-sandbox-client-control-channel.md`.
