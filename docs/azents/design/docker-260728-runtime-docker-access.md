---
title: "Complete Runtime Docker Access Design"
created: 2026-07-28
updated: 2026-07-28
implemented: 2026-07-28
tags: [runtime, docker, provider, backend, frontend, infra, testing]
document_role: primary
document_type: design
snapshot_id: docker-260728
---

# Complete Runtime Docker Access Design

- Snapshot: `docker-260728`
- Document reference: `docker-260728/DESIGN`
- Requirements: [Complete Runtime Docker Access Requirements](../requirements/docker-260728-runtime-docker-access.md) (`docker-260728/REQ`)
- ADR: [Complete Runtime Docker Access](../adr/docker-260728-runtime-docker-access.md) (`docker-260728/ADR`)

## Policy contract

The canonical policy document contains exactly `schema_version`, `docker`, and `resources`.
`docker/v1` contains `enabled`, `storage_mode`, and `storage_capacity_bytes`.
`runtime.resources/v1` contains optional Kubernetes CPU/memory requests and limits, one optional
Runtime ephemeral-storage allocation, and optional Workspace persistent storage. PID, container
count, and per-Profile network fields do not exist.

Workspace and Agent restrictions can disable Docker as a whole, narrow Docker storage, or tighten
outer resource values. Docker enablement plus its storage mode and capacity are classified and
projected atomically during automatic convergence.

## Kubernetes topology

A Docker-enabled Runtime Pod contains `runner` and `container-engine` containers. The engine is the
privileged DIND sidecar. Both containers share a memory-backed socket directory; Runner mounts it
read-only and receives:

- `DOCKER_HOST=unix:///var/run/azents-engine/docker.sock`
- `TESTCONTAINERS_HOST_OVERRIDE=127.0.0.1`
- `TESTCONTAINERS_CONNECTION_MODE=docker_host`
- `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/azents-engine/docker.sock`

The engine owns its separate bounded `emptyDir` data directory. The configured CPU, memory, and
ephemeral-storage resources apply directly to the engine without reserving a Gateway share.
Runner remains unprivileged and retains only its Workspace PVC plus the private engine socket.

Each Runtime NetworkPolicy permits required DNS and Runtime Control traffic, IPv4/IPv6 outbound
traffic, deployment hard-cap CIDR exclusions and exceptions, and deployment-owned selector/port
rules. No Profile network value participates in this calculation.

## Migration

The head Alembic revision rewrites Profile, Workspace, Agent, and snapshot documents. Any previous
build/run/Compose enablement becomes `docker.enabled=true`; old engine storage becomes Docker
storage. Removed network, PID, and container-count values are discarded. Snapshot target digests
are recalculated, prior reported evidence is cleared, application state returns to pending, and
applied snapshot pointers are cleared so the new exact v1 evidence is reconciled.

Downgrade intentionally does not recreate the lossy old policy data. This is a replacement of an
unreleased contract, not a backward-compatible release transition.

## Product surfaces

Admin Profile editing presents one Docker section, temporary Docker data capacity, Kubernetes
sidecar resources, Workspace persistent storage, and a read-only explanation of deployment-owned
outbound access. Public Workspace/Agent restrictions present only truthful narrowing controls.
Status summaries expose one Docker capability and its storage metadata.

## Test Strategy

### E2E primary verification matrix

- Docker CLI: daemon version, image build, container run, and Compose lifecycle.
- Docker SDK: ping/version plus container lifecycle without request-header filtering.
- Testcontainers: Network create/remove, PostgreSQL container with port binding, and Ryuk cleanup.
- Azents: one focused deterministic E2E using the Runtime-private Docker endpoint.

### Provider and contract verification

- Runtime Control parser rejects all removed fields and accepts only the canonical v1 shape.
- Resolver tests cover atomic Docker enable/disable, restriction, storage, resources, and Provider
  compatibility.
- Kubernetes Provider tests assert the two-container topology, direct read-only Runner socket mount,
  Testcontainers environment, engine resources, storage, and static NetworkPolicy hard cap.
- Migration tests validate representative full policies, restrictions, digests, and snapshot
  invalidation.

### Execution policy

Deterministic unit and integration tests run in CI. Docker workflow tests require a working
privileged DIND environment and fail when the Docker endpoint exists but ordinary workflows do not
work; they may be skipped only when no Docker prerequisite is available. Evidence records command,
client, daemon version, operation outcome, and cleanup without credentials or socket contents.
