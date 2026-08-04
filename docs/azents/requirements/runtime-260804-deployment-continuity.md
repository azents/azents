---
title: "Runtime Deployment Continuity Requirements"
created: 2026-08-04
updated: 2026-08-04
implemented: 2026-08-04
tags: [runtime, backend, provider, reliability]
document_role: primary
document_type: requirements
snapshot_id: runtime-260804
---

# Runtime Deployment Continuity Requirements

- Snapshot: `runtime-260804`
- Document reference: `runtime-260804/REQ`

## Problem

A healthy Agent Runtime can become unavailable after Runtime Control or Runtime
Provider deployment even though its backend workload remains running and ready.
The persisted Runtime state can regress to a lifecycle transition that did not
occur, and the Runtime may remain unusable until a user performs a Force Restart.

## Primary Actor

An Agent user whose Agent Runtime is healthy and actively available while Runtime
control-plane components are deployed or reconnect.

## Primary Scenario

A coordinated Runtime Control and Runtime Provider deployment replaces the
control-plane processes while an existing Agent Runtime workload remains healthy.
After the bounded transport reconnection to the current protocol version, the
Runtime remains represented by its actual backend lifecycle state, resumes
operation routing without a user-initiated restart, and converges independently
observed backend drift through normal control-plane reconciliation.

## Supporting Scenarios

- A managed backend resource drifts while the Runtime workload remains healthy.
- A Provider reconnects with a new transport generation while existing Runtime
  resources retain historical command-generation metadata.
- Runtime Control restarts after drift has been observed but before repair has
  completed.

## Goals

- Keep healthy Runtime workloads usable across control-plane deployment and
  reconnection.
- Keep persisted and user-visible lifecycle state truthful to actual backend state.
- Detect and repair managed backend drift without making Provider process-local
  state a lifecycle authority.
- Preserve Agent Workspace data through observation, reconciliation, and
  deployment recovery.

## Non-Goals

- Guarantee that an individual in-flight Runner operation survives a temporary
  transport disconnect.
- Remove the bounded transport reconnection window during a coordinated
  deployment.
- Change explicit Runtime reset or terminal-delete semantics.
- Introduce Provider fallback, legacy protocol fallback, or another Runtime
  lifecycle authority.

## Requirements

### REQ-1. Truthful backend observation

Provider observation must report the actual backend lifecycle independently from
whether the Provider process previously handled a command for that Runtime.

**Acceptance criteria**

- A running and ready backend workload is observed as running after Provider
  restart or reconnection.
- Missing Provider process-local history cannot change a running observation into
  a starting, recovering, stopped, or failed lifecycle state.
- Observation does not mutate backend resources.

### REQ-2. Deployment continuity

A control-plane deployment must not require a user-initiated Runtime restart when
the Runtime backend workload and current Runner remain healthy.

**Acceptance criteria**

- After the Provider and Runner routes reconnect, ordinary Runtime operations
  resume without Force Restart.
- User-visible Runtime state does not regress solely because a Provider or Runtime
  Control connection generation changed.
- A bounded temporary transport disconnect remains represented as transport
  availability rather than a fabricated backend lifecycle transition.
- A Kubernetes Provider using an obsolete protocol version cannot regain
  connection or command authority from current Runtime Control.

### REQ-3. Durable drift reconciliation

Managed backend drift must be represented independently from lifecycle state and
must remain available to Runtime Control until it is repaired, invalidated by a
new authoritative generation, or replaced by newer observation.

**Acceptance criteria**

- Runtime Control can distinguish an in-sync Runtime, an observed drift, and the
  absence of authoritative drift evidence.
- A Runtime Control restart does not lose current generation-matched drift that
  still requires repair.
- A lifecycle-only watch report cannot erase newer authoritative drift evidence.

### REQ-4. Control-owned repair decisions

Runtime Control must own whether and how observed drift triggers a lifecycle or
configuration command.

**Acceptance criteria**

- Providers report observed facts and drift but do not select the lifecycle repair
  command.
- Runtime Control maps supported drift to an idempotent, bounded repair action.
- Missing or stale drift evidence causes fresh read-only observation rather than
  an inferred lifecycle transition.

### REQ-5. Generation-fenced authority

Provider and Runner connection generations must fence transport freshness without
becoming durable Runtime lifecycle or desired-configuration authority.

**Acceptance criteria**

- Drift and lifecycle reports are accepted only for valid Provider and desired
  generations.
- Drift observed for an older Provider connection or desired Runtime generation
  cannot trigger repair for a newer generation.
- Existing backend resource labels containing historical Provider generations do
  not require workload replacement by themselves.

### REQ-6. Workspace-preserving recovery

Deployment recovery and automatic drift repair must preserve Agent Workspace data.

**Acceptance criteria**

- Observation never deletes or replaces Runtime storage.
- Automatic repair uses only existing non-destructive lifecycle and
  configuration-application boundaries.
- PVC or host-directory deletion remains limited to explicit reset and terminal
  delete.

## Fixed Constraints

- Kubernetes and Docker Providers remain external components without direct
  access to Azents server repositories or database sessions.
- `observe` remains read-only.
- Runtime Control remains the durable desired-state and reconciliation authority.
- Provider and Runner connection generations remain transport fences.
- Start, restart, recover, and automatic reconciliation preserve Agent Workspace
  data.
- No backward-compatibility, mixed-version support, or legacy fallback path is
  added. Runtime Control and Providers use one current report contract.
- Current Runtime Control accepts only the exact supported Kubernetes Provider
  protocol version before granting connection or command authority.

## Open Assumptions

- The current periodic Runtime Control reconciliation cadence is sufficient to
  establish fresh drift evidence after a Provider reconnect.
- Initial implementation may make Kubernetes NetworkPolicy drift the first
  actionable structured drift while other Providers report no authoritative drift
  evidence until they implement equivalent comparison.

## Confirmation

Confirmed by the requester on 2026-08-04 through the instruction to implement the
previously agreed Provider-observation and Runtime-Control-reconciliation boundary
and open a pull request.
