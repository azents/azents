---
title: "Complete Runtime Docker Access"
created: 2026-07-28
updated: 2026-07-28
implemented: 2026-07-28
tags: [runtime, docker, provider, security, architecture]
document_role: primary
document_type: adr
snapshot_id: docker-260728
---

# Complete Runtime Docker Access

- Snapshot: `docker-260728`
- Document reference: `docker-260728/ADR`
- Requirements: [Complete Runtime Docker Access Requirements](../requirements/docker-260728-runtime-docker-access.md) (`docker-260728/REQ`)

## Context

The Container Policy Gateway converted a broadly understood Docker capability into a proprietary
partial API. Compatibility failures were inherent: accepting new client headers or request fields
did not make the underlying operation safe, while rejecting them broke routine development tools.
The initial product decision already accepted privileged DIND risk and reserved rootless isolation
for later work.

## Decision

### docker-260728/ADR-D1: Remove the Container Policy Gateway

The Runner connects directly to the Unix socket of the privileged DIND sidecar in the same Runtime
Pod. The Provider does not interpret, filter, or rewrite Docker HTTP requests.

### docker-260728/ADR-D2: Treat Docker authority atomically

`docker/v1` is one capability. Enabling it grants build, run, Compose, Docker SDK, Testcontainers,
Ryuk, port bindings, and other daemon-supported workflows. The product does not claim granular
security boundaries inside that authority.

### docker-260728/ADR-D3: Remove unenforceable policy fields

PID, nested container count, Docker request filtering, and Profile network modes are removed from
the policy contract and UI. They cannot be truthful hard caps with a direct privileged Docker
socket.

### docker-260728/ADR-D4: Keep Kubernetes-owned boundaries

The Docker sidecar receives Profile-selected Kubernetes CPU/memory requests and limits plus an
ephemeral-storage request and limit. Docker private data capacity and Workspace PVC capacity remain
separate. The installation NetworkPolicy stays a deployment-owned hard cap applied to the Runtime
Pod.

### docker-260728/ADR-D5: Model safer isolation as a separate implementation

Privileged DIND is explicitly unsafe by design. Rootless DIND or stronger isolation must be a
separate Provider implementation/capability with its own qualification, not a hidden restriction
layer on the privileged implementation.

### docker-260728/ADR-D6: Replace the unreleased contract in place

All current policy and protocol modules remain version 1. Stored data is migrated to the new v1
shape and old fields are removed without a compatibility parser. A formal post-release contract
change will introduce a new version.

## Superseded decisions

This snapshot supersedes the policy-Gateway enforcement, granular container-operation capability,
Profile network-mode, nested PID/count enforcement, and gateway-resource decisions in
`runtime-260726/ADR`. It also supersedes any unchanged carry-forward of those decisions in
`runtime-260727/ADR`. Profile-only authority, explicit Apply, immutable snapshots, Workspace PVC
lifecycle, and deployment hard-cap decisions remain in force.

## Consequences

- Docker-enabled code has full control of its Runtime-private privileged daemon.
- Nested Docker containers are not individual Kubernetes workloads and do not receive individual
  Kubernetes resource policy.
- Compatibility follows the Docker daemon API rather than an Azents allowlist.
- The UI and contract no longer imply controls that the Provider cannot enforce.
