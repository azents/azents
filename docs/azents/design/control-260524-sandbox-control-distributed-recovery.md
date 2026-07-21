---
title: "Sandbox Provider Control Distributed Recovery"
created: 2026-05-24
updated: 2026-05-24
implemented: 2026-05-24
tags: [backend, engine, infra, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: control-260524
migration_source: "docs/azents/design/sandbox-provider-control-distributed-recovery.md"
historical_reconstruction: true
---

# Sandbox Provider Control Distributed Recovery

## Context

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

## Non-Goals

- Replace Redis Pub/Sub with a durable command log in this PR.
- Change K8s `/home/sandbox` persistence semantics.
- Introduce provider-native PVC or node-local persistence for the K8s provider.
- Change provider identity or sandbox-control auth-token protocol.

## Design

### 1. Treat Command Timeout As Unknown, Not Failed

`allocate_runtime` timeout means the caller did not receive the command result. It
does not prove the provider failed. After timeout, `ProviderControlSessionSandboxClient`
checks the runtime command plane:

1. Wait briefly for `SandboxControlWorker.wait_ready(agent_runtime_id)`.
2. If the runtime stream is ready and the active lease generation still matches the
   allocation generation, transition the lease through `STARTING` to `RUNNING`.
3. Return success to the runtime manager.
4. If the runtime stream is not ready, mark the active lease `LOST` and let the outer
   retry loop allocate again.

This covers the observed case where Kubernetes created a Pod and the sandbox client
connected, but provider-controller or sandbox-control was evicted before the operation
result returned to the worker.

### 2. Existing Active Lease Semantics

`sandbox_runtime_leases` is the provider allocation authority. The allocation path
must not blindly insert a new `ALLOCATING` lease when any active lease already exists.

- `STARTING`, `RUNNING`, and `HIBERNATING` are treated as already allocated or
  in-progress.
- Active `ALLOCATING` or `DELETING` with a future `expires_at` is treated as an
  allocation in progress. The caller waits until its own deadline instead of inserting
  a duplicate active lease.
- Expired active lease is marked `LOST` and retried with a new generation.

### 3. Stale Lease Recovery

The lifecycle manager already clears stale `agent_runtimes` run leases. It must also
recover provider runtime leases:

- On manager startup, mark expired active `sandbox_runtime_leases` as `LOST`.
- On each stale lease lifecycle tick, do the same in bounded batches.

This prevents an old `ALLOCATING` row from permanently blocking allocation through the
partial unique index on active runtime leases.

### 4. K8s Control-Plane Availability

Correctness is handled by idempotency and reconciliation, but K8s control-plane
components should still be deployed with a reasonable availability floor:

- `sandbox-control` runs with two replicas, HPA `minReplicas: 2`, and PDB
  `maxUnavailable: 1`.
- `sandbox-provider-controller` runs with two replicas, HPA `minReplicas: 2`, and PDB
  `maxUnavailable: 1`.

Multiple provider-controller replicas are safe because provider registration is
generation-fenced. Only the active owner for the current provider generation handles a
matching command, and stale observations/results are fenced by lease generation.

### 5. Remaining Durable Command Log Gap

Redis Pub/Sub is still an at-most-once command transport. The implemented timeout
recovery handles side effects that completed but lost their operation result, and retry
handles commands that were lost before side effects. The next hardening step should
replace Pub/Sub request/reply with a durable command log, for example Redis Streams or
a database-backed provider operation table:

- command id stored before publish
- provider id/runtime id/generation fencing in the command record
- idempotent provider ack/result write
- retry or reconciliation worker for pending commands
- result consumers that can resume after caller restart

This follow-up is not required to close the current production failure because runtime
readiness and lease reconciliation now converge the ambiguous cases.

## Failure Matrix

| Failure | Expected behavior |
| --- | --- |
| Provider command lost before owner receives it | Request times out, lease becomes `LOST`, retry creates a new generation. |
| Provider creates Pod but operation result is lost | Runtime stream readiness proves success, lease becomes `RUNNING`. |
| sandbox-control Pod evicted during allocation | Provider/runtime reconnect; caller either observes ready runtime or retries. |
| provider-controller Pod evicted during allocation | Existing Pod is reused or recreated by a later generation; stale result is ignored. |
| Old `ALLOCATING` lease remains after crash | Startup/tick stale recovery marks it `LOST`. |
| Concurrent allocation for same runtime | Active lease check prevents duplicate active inserts. |

## Test Strategy

Primary product validation is E2E:

- Start provider-control backed K8s or system Docker provider.
- Trigger sandbox allocation.
- Kill/restart sandbox-control or provider-controller during allocation.
- Verify the user-visible sandbox command eventually succeeds and no duplicate active
  runtime lease remains.

Unit and static validation in this PR:

- Provider-control client tests cover active/expired `ALLOCATING` leases.
- Provider-control client tests cover operation-result timeout with ready and not-ready
  sandbox-control runtime streams.
- Session sandbox manager tests cover stale provider lease recovery.
- Kustomize/Helm manifests include HPA/PDB availability controls.

CI should run deterministic unit/type/static checks. Live K8s disruption E2E remains
environment-gated because it needs a live provider-control Kubernetes environment and
permission to delete/evict control-plane Pods.
