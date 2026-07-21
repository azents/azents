---
title: "Idempotent Sandbox Lifecycle State Design"
created: 2026-05-24
updated: 2026-05-24
tags: [backend, engine, infra, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: idempotent-260524
migration_source: "docs/azents/design/idempotent-sandbox-lifecycle.md"
historical_reconstruction: true
---

# Idempotent Sandbox Lifecycle State Design

## Problem

Sandbox lifecycle control currently mixes desired-state changes, provider lease
allocation, process-local attach, and Kubernetes Pod reconciliation behind
`ensure_ready()`. That makes a harmless user/API action such as "start sandbox"
able to produce a fresh provider allocation. In the K8s provider this can delete
and recreate the sandbox Pod when the existing Pod's provider generation/token
does not match the new allocation.

That is unsafe because the K8s provider mounts `/home/sandbox` as Pod-local
`emptyDir`. If a Pod is deleted before a checkpoint is committed, user-visible
workspace data is lost.

## Goals

- Sandbox state changes are idempotent desired-state transitions.
- Worker/API code does not decide whether to create, delete, or recreate K8s
  Pods.
- Kubernetes provider remains the resource reconciler for desired runtime state.
- ACTIVE runtime attach is non-destructive and never allocates a new backend.
- Persist/restore transitions are data-safe and retryable.
- Destructive recovery is explicit and gated by a durability precondition:
  checkpoint exists, provider-native `preserve_home`, or operator/user-approved
  discard.

## Responsibility Boundaries

### Worker and API server

Worker/API owns product intent and access control. It may request that an
AgentRuntime should be running or stopped, but it must not make Pod-level
decisions.

- `start sandbox` means "ensure desired runtime state is running".
- Repeating `start sandbox` while the AgentRuntime is ACTIVE is a no-op.
- API read paths may attach to an already ACTIVE runtime, but attach must only
  verify sandbox-control readiness and install process-local handles.
- API read paths must not allocate or recreate provider resources.

### SessionSandboxManager

The manager owns AgentRuntime lifecycle state and durability policy.

- `get_or_allocate_runtime()` is the start/resume allocator. It may create a
  runtime only when the AgentRuntime is not already ACTIVE.
- `attach_active_runtime()` is a distinct non-destructive operation. It is used
  when another process already started the runtime and the current process only
  needs a local handle.
- `get_file_storage()` is a read/attach operation. It must not call provider
  allocation.
- Hibernation owns checkpoint-before-delete ordering.
- Restore owns checkpoint-before-fresh-fallback ordering. Provider/control
  unavailability is not checkpoint corruption and must not invalidate checkpoint
  metadata or fall back to an empty workspace.

### Provider-control client

Provider-control owns provider lease and command routing, not product desired
state. A lost provider lease alone is not permission to destroy user workspace
state.

- Allocation commands are only issued from explicit start/resume paths.
- Observation/lease reconciliation reports health and ownership.
- Ambiguous provider-command outcomes may be recovered by sandbox-control
  readiness probing, but must not turn an ACTIVE runtime into a fresh
  allocation without manager durability policy.
- Provider/control timeouts during restore are infrastructure availability
  failures. They are retryable and must not mark a checkpoint expired.

### Kubernetes provider

Kubernetes provider is the reconciler for K8s resources. It may create/delete
Pods only to converge the desired provider runtime state given by the control
plane. It does not own user workspace durability.

- `/home/sandbox` is Pod-local `emptyDir` today.
- Pod delete/recreate is destructive unless a checkpoint or provider-native
  preservation exists.
- Spec drift for an ACTIVE runtime must be surfaced as health/drift evidence,
  not silently fixed by deleting the Pod from an API start/read path.

### Sandbox-control

Sandbox-control owns runtime command/file/checkpoint streams for an already
running sandbox. Its readiness is the attach signal for ACTIVE runtimes.

## State Transition Rules

| Current AgentRuntime state | Request | Behavior |
|---|---|---|
| `None` | start | Fresh allocate is allowed. |
| `ACTIVE` | start | Idempotent no-op or non-destructive attach. No allocation. |
| `ACTIVE` | workspace read | Non-destructive attach. No allocation. |
| `ACTIVE` + control unavailable | start/read | Return transitional/unavailable state. Do not recreate Pod. |
| `HIBERNATED` | start | Restore from checkpoint or provider preserved home. |
| `EXPIRED` | start | Fresh start is allowed only because durable state is already declared expired. |
| `PERSISTING`/`RESTORING` | start/read | Return transitional state. |

## Persist and Restore Stability

Persist and restore are not best-effort conveniences; for K8s `emptyDir` they
are the durability boundary.

### Persist invariants

- The manager transitions `ACTIVE -> PERSISTING` before checkpoint creation.
- For K8s/checkpoint providers, checkpoint upload and metadata commit must
  succeed before provider `DeleteRuntime(preserve_home=false)` is sent.
- If checkpoint creation, upload, metadata commit, or provider checkpoint
  readiness fails, the manager restores the runtime state to `ACTIVE` with a
  retry deadline and leaves compute running when it can.
- If provider delete fails after checkpoint commit, the checkpoint remains valid
  and the runtime is retried by reconciliation. The checkpoint is not rolled
  back because it is now the durable copy.
- For provider-native preservation (`preserve_home=true`), provider delete may
  happen without S3 checkpoint only because the provider is the durable home
  authority.

### Restore invariants

- Restore starts only from `HIBERNATED` or `EXPIRED` policy paths, never from
  `ACTIVE` attach paths.
- For K8s/checkpoint providers, restore requires a latest valid checkpoint row.
  Missing checkpoint means the runtime is `EXPIRED` or restore-failed, not an
  implicit empty fresh workspace.
- Provider unavailable, command timeout, allocation timeout, and sandbox-control
  stream timeout are retryable restore infrastructure failures. They do not
  invalidate checkpoint rows and do not trigger empty fresh fallback.
- Checkpoint invalidation is reserved for checkpoint-object evidence:
  object missing, checksum mismatch, archive corruption, or restore command
  failure after bytes are fetched into the runtime.
- Fresh fallback after failed restore is allowed only when the runtime is already
  `EXPIRED` or an explicit discard policy has been chosen.

## Implementation Plan

1. Split attach from allocation.
   - `SessionSandboxManager.attach_active_runtime()` waits for existing
     sandbox-control stream and installs a local handle.
   - It does not call provider `ensure_ready()`.
2. Make Session Workspace read/start ACTIVE-safe.
   - If DB says the current session's AgentRuntime is `ACTIVE`, call
     `attach_active_runtime()`.
   - If attach fails, return a transitional state and do not call
     `get_or_allocate()`.
3. Make file storage read-only with respect to provider resources.
   - `get_file_storage()` only resolves the local handle and waits for
     sandbox-control.
   - It does not allocate or recreate a backend.
4. Harden restore failure boundaries.
   - Provider/control unavailability during restore returns retryable failure.
   - Checkpoint rows are preserved unless checkpoint bytes are proven invalid.
   - Missing checkpoint does not silently start an empty workspace from a
     `HIBERNATED` state.
5. Add regression tests.
   - Workspace panel renders READY by attaching to an ACTIVE runtime created by
     another process.
   - Start on ACTIVE runtime attaches without reallocating.
   - Attach failure on ACTIVE runtime does not fall back to allocate.
   - Manager attach does not call provider ensure/delete.
   - Restore provider unavailable keeps checkpoint metadata and does not fresh
     allocate an empty workspace.
   - Persist failure does not delete provider compute.
6. Update living specs to encode idempotent state-change and K8s data
   durability boundaries.

## Non-goals

- Adding a new `desired_runtime_state` database column in this PR.
- Changing provider-control protocol messages in this PR.
- Introducing provider-native K8s persistent volumes in this PR.

Those are follow-up hardening items. The immediate safety fix is to stop
ACTIVE start/read paths from invoking allocation/recreate.

## Test Strategy

### E2E Primary Matrix

| Behavior | Primary E2E expectation |
|---|---|
| Start while ACTIVE | Repeated start leaves the same sandbox workspace contents intact. |
| Workspace panel on another replica | Panel shows READY for an ACTIVE runtime created by worker/tool execution. |
| ACTIVE attach failure | UI does not recreate Pod; it reports a transitional/unavailable state. |
| Hibernated restore | Start restores from checkpoint or provider preserved home. |
| Restore infra failure | Checkpoint remains valid and no empty workspace is allocated. |
| Persist failure | Pod/container is not deleted before checkpoint commit. |

### Local/Unit Coverage

- Unit tests cover manager attach, workspace read attach, start idempotency,
  attach-failure no-reallocate behavior, persist-before-delete ordering, and
  restore failure boundaries.
- Provider-control live E2E should add same-runtime file preservation evidence:
  create file, click/start again, verify file remains and Pod UID does not
  change.

### Testenv and Prerequisites

No new credential snapshot is required for unit coverage. Live K8s/provider
E2E continues to use the existing `sandbox-provider-control` prerequisite
snapshot. If that prerequisite is missing in local or PR environments, live E2E
must skip or fail according to the existing provider-control policy; it must not
fake a PASS.

### Evidence

Live evidence should include:

- AgentRuntime id and current session id.
- Sandbox Pod UID before/after repeated start.
- `/home/sandbox` sentinel file path and content hash before/after repeated
  start.
- Provider lease state before/after repeated start.

Raw provider-control tokens, sandbox-control auth tokens, and presigned URLs
must not appear in evidence.
