---
title: "Complete Runtime Docker Access Requirements"
created: 2026-07-28
updated: 2026-07-28
implemented: 2026-07-28
tags: [runtime, docker, provider, security, policy]
document_role: primary
document_type: requirements
snapshot_id: docker-260728
---

# Complete Runtime Docker Access Requirements

- Snapshot: `docker-260728`
- Document reference: `docker-260728/REQ`

## Problem

The Kubernetes Runtime advertised Docker support while a Container Policy Gateway accepted only a
small subset of Docker API requests. Ordinary Docker SDK and Testcontainers workflows failed on
client headers, port bindings, and other API fields even though Docker was enabled. PID and nested
container-count settings also appeared enforceable despite the direct Docker authority expected by
the product.

## Primary scenario

An Admin enables Docker in a Runtime execution Profile. The resulting Runtime supports normal
Docker CLI, Docker Compose, Docker SDK, Testcontainers, and Ryuk workflows through its private DIND
daemon without application-specific protocol filtering.

## Requirements

### REQ-1. Docker is one complete capability

Expose one Docker enablement setting. Do not separately advertise or gate image build, container
run, or Compose operations.

### REQ-2. Remove false nested-workload controls

Remove PID, nested container-count, per-request Docker API, and Profile network-mode restrictions
that cannot be reliably enforced after granting direct Docker daemon authority.

### REQ-3. Preserve enforceable outer boundaries

Profiles may configure Kubernetes CPU and memory requests and limits, Runtime ephemeral storage,
Docker private data storage, and Workspace persistent storage. The deployment-owned Kubernetes
NetworkPolicy remains an installation hard cap and is not Profile-configurable.

### REQ-4. Direct private DIND compatibility

Each Docker-enabled Runtime exposes only its own DIND socket to its Runner. The socket must support
ordinary Docker clients without a compatibility proxy, including port binding and client-managed
containers.

### REQ-5. Explicit security posture

Document privileged DIND as the intentionally unsafe initial Docker implementation. A safer
rootless implementation is future Provider work, not a compatibility mode inside this contract.

### REQ-6. Clean v1 replacement

Migrate stored policies and snapshots to one v1 `docker` module and one v1 `runtime.resources`
module. Do not retain a legacy parser or compatibility contract. Existing granular Docker flags
migrate to enabled when any old Docker operation was enabled.

## Non-goals

- Making privileged DIND safe for mutually untrusted workloads.
- Enforcing nested-container resource or network policy through Docker API filtering.
- Providing persistent Docker daemon data in the Kubernetes Provider.

## Confirmation

Confirmed by the requester on 2026-07-28, including feature-dropping the Gateway and removing
unenforceable limits without backward compatibility.
