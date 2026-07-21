---
title: "Introduce SandboxProviderControl"
created: 2026-05-21
tags: [architecture, backend, engine, infra, security, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: sandbox-260521
historical_reconstruction: true
migration_source: "docs/azents/adr/0035-sandbox-provider-control.md"
---

# sandbox-260521/ADR: Introduce SandboxProviderControl

## Context

[sandbox-260506/ADR](./sandbox-260506-sandbox-control-channel.md) adopted a structure where an in-sandbox client opens an outbound `SandboxControlRuntime.Connect` gRPC stream to NoIntern, and the worker requests command/file/checkpoint operations through `SandboxControlWorker`. This decision separated command/file/checkpoint transport from Kubernetes Pod IP, Docker network discovery, and inbound sidecar daemon calls.

However, the sandbox **lifecycle provider** still has NoIntern worker/control plane directly creating Kubernetes Pods or local Docker containers. This structure does not sufficiently express the following requirements:

1. Providers outside the NoIntern-managed Kubernetes cluster must be able to provide sandbox capacity.
2. To support customer/local Docker providers long term, the provider must connect outbound to NoIntern without exposing inbound ports.
3. K8s-based provider controller should be separated as an optional component in the NoIntern Helm chart so operational topology is explicit.
4. Provider identity, active liveness, runtime allocation lease, and sandbox-control runtime registration auth must have separate state authorities.
5. The durable contract preserved on hibernate/resume must clearly distinguish `/home/sandbox/**` from rootfs/S3 snapshot/container snapshot.

In issue #3914 Phase 2 design discussion, we decided to first settle the direction of SandboxProviderControl and leave detailed local Docker provider UX/daemon implementation downstream.

## Decision

Adopt the following decisions.

1. The first SandboxProvider implementation is **K8s-first**, not local Docker-first.
2. K8s provider is an **out-of-process provider controller**, not an implementation inside the NoIntern server process. Its deployment unit targets an optional component of the NoIntern Helm chart.
3. SandboxProviderControl is a **bidirectional reverse gRPC stream** opened outbound from provider controller/daemon to NoIntern. Service name is `SandboxProviderControl`, and the main RPC is `ConnectProvider`.
4. Provider state taxonomy has two axes:
   - static vs dynamic
   - system vs user/workspace
5. Source of truth for static + system provider is config/Helm. Source of truth for other dynamic providers is DB. Active connection/liveness for both cases lives in Redis registry.
6. Runtime provider allocation state is not added as `agent_runtimes` columns; it lives in a separate active-lease table, `sandbox_runtime_leases`.
7. In K8s-first migration, introduce `SandboxControlAuthToken`. This value is mandatory, not optional, and is passed through sandbox-control runtime `RegisterRequest.auth_token` field. Do not put it in gRPC metadata.
8. K8s-first migration preserves existing filesystem semantics of the embedded K8s Pod manager. In K8s, `/home/sandbox/**` hibernate/resume durability continues to be handled by the existing S3/RustFS checkpoint tar flow.
9. Provider-native home preservation may become a future provider capability, but #3914 K8s provider porting does not introduce new persistence backends such as PVC/object-backed volume.
10. #3914 is a protocol/abstraction/security prerequisite for local Docker provider. Detailed local Docker UX, daemon packaging, Docker hardening, and customer onboarding are downstream requirements outside this ADR.

This ADR records target architecture before implementation. The S3/RustFS checkpoint authority described in `docs/nointern/spec/flow/sandbox-checkpoint-lifecycle.md` remains current system spec after K8s provider porting. Provider-native `/home/sandbox` preservation will be handled in follow-up design as a separate provider capability.

## Considered Options

### K8s-first provider controller

Adopted. Kubernetes is the current primary production sandbox backend, and Helm packaging design already covers the boundary between `server.sandboxControl` and `sandbox` components. Externalizing K8s provider controller first lets us verify provider-control protocol, runtime lease, auth token, and liveness registry in production-like topology.

### Local Docker-first provider daemon

Rejected. Local Docker provider is an important downstream goal, but it has many concerns: customer machine trust boundary, Docker socket hardening, credential UX, and persistent volume policy. Implementing local UX before protocol/abstraction/security contract risks diverging from the K8s operations path.

### Keep direct Kubernetes API calls from NoIntern worker

Rejected. This is closest to current structure, but it does not create provider abstraction and cannot easily represent optional Helm component or external provider connection.

### Store all provider state in DB

Rejected. Provider identity and policy can have DB or config as source of truth, but active stream owner/liveness is ephemeral state that needs TTL and heartbeat. Redis registry fits, same as existing sandbox-control connection registry.

### Store runtime allocation provider in `agent_runtimes` columns

Rejected. Runtime lifecycle state and provider allocation lease differ in update frequency, failure recovery, and fencing semantics. They must be separated into `sandbox_runtime_leases` active-lease table to safely handle allocation retry and provider reconnect.

### Pass SandboxControlAuthToken through gRPC metadata

Rejected. Keep it in `RegisterRequest.auth_token` field so sandbox-control runtime registration's durable handshake payload is managed as audit/test/codegen contract.

## Consequences

### Positive

- K8s lifecycle control can be separated from NoIntern core worker process and deployed as an optional Helm component.
- Local Docker provider can later be implemented on the same provider-control protocol.
- Authorities are separated for provider identity, provider liveness, runtime allocation lease, and sandbox-control runtime auth token.
- K8s provider-control cutover does not change existing S3/RustFS checkpoint-based hibernate/resume semantics.
- Both provider controller and sandbox container use outbound-first connections, reducing inbound exposure in private cluster/customer networks.

### Negative

- Adds SandboxProviderControl proto, provider registry, active lease table, and auth token issuance/validation.
- Version compatibility between K8s provider controller and NoIntern server/control plane must be managed.
- Helm chart adds optional provider controller component and related secret/config wiring.
- Failure recovery becomes more complex than existing single backend client. Provider stream disconnect, stale runtime lease, and sandbox-control stream readiness must be reconciled separately.
- Existing `SessionSandboxClient` naming/API and runtime lifecycle manager must be cleaned up to accept provider abstraction.

## Status

Accepted. Detailed design draft follows `docs/nointern/design/sandbox-provider-control.md`.

## Migration provenance

- Historical source filename: `0035-sandbox-provider-control.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
