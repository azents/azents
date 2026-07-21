---
title: "Sandbox Provider Control Distributed Recovery Historical Requirements Reconstruction"
created: 2026-05-24
implemented: 2026-05-24
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: control-260524
historical_reconstruction: true
migration_source: "docs/azents/design/sandbox-provider-control-distributed-recovery.md"
---

# Sandbox Provider Control Distributed Recovery Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `control-260524`
- Source: `docs/azents/design/control-260524-sandbox-control-distributed-recovery.md`
- Historical source date basis: `2026-05-24`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Sandbox provider-control split runtime lifecycle across worker, sandbox-control,
provider controller, Redis, PostgreSQL, and the runtime Pod/container. This is a
distributed system: any control-plane Pod can be evicted, a reverse gRPC stream can
disconnect after a side effect, Redis Pub/Sub can drop an in-flight response, and the
Kubernetes API can create a Pod even when the original caller times out.

The production failure on 2026-05-24 exposed two weak assumptions:

1. Provider command request/response was treated like a reliable RPC even though the
   transport is Redis Pub/Sub plus process-local gRPC stream ownership.
2. Provider allocation success was tied to receiving an operation result, even when
   the runtime Pod and sandbox-control runtime stream were already alive.

PDB/HPA can reduce voluntary disruption frequency, but correctness must not depend on
a specific sandbox-control or provider-controller Pod surviving.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Runtime allocation must be idempotent and converge after command result loss.
- Existing active `sandbox_runtime_leases` must be interpreted as in-progress,
  running, hibernating, deleting, or stale rather than causing duplicate active lease
  inserts.
- Expired provider runtime leases must be recovered during startup and lifecycle
  ticks.
- K8s provider-control components must maintain at least two replicas and tolerate one
  voluntary disruption.
- Docker provider behavior must stay compatible with the same provider-control path.

## Non-goals

- Replace Redis Pub/Sub with a durable command log in this PR.
- Change K8s `/home/sandbox` persistence semantics.
- Introduce provider-native PVC or node-local persistence for the K8s provider.
- Change provider identity or sandbox-control auth-token protocol.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
