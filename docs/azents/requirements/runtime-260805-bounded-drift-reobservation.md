---
title: "Runtime Bounded Drift Re-observation Requirements"
created: 2026-08-05
updated: 2026-08-05
implemented: 2026-08-05
tags: [runtime, backend, provider, reliability]
document_role: primary
document_type: requirements
snapshot_id: runtime-260805
---

# Runtime Bounded Drift Re-observation Requirements

- Snapshot: `runtime-260805`
- Document reference: `runtime-260805/REQ`

## Problem

Runtime Control currently persists a managed-resource drift projection and repair
claim for each Runtime. NetworkPolicy drift is a convergent, idempotent condition,
so retaining that observation as durable Runtime state adds authority and recovery
complexity without improving the bounded periodic recovery users require.

## Primary Actor

An Agent user whose healthy Runtime has a managed NetworkPolicy drift while Runtime
Control and its Provider may restart or reconnect.

## Primary Scenario

Periodic Runtime Control observation finds NetworkPolicy drift for a healthy
running Runtime. Control issues one non-destructive repair promptly. If the
observation, dispatch, or Control process is lost before repair completes, a later
periodic observation rediscovers the drift and retries without user action.

## Supporting Scenarios

- Runtime Control restarts after an observation and before the repair command is
  delivered.
- A Provider reconnects with a new generation while prior command completion is
  unavailable.
- A repair command completes without convergence; a later observation retries it.

## Goals

- Keep backend lifecycle observation truthful and independent from managed-resource
  drift.
- Repair supported current drift promptly without recording drift as durable
  Runtime state.
- Bound recovery after observation or command loss by the periodic observation
  cadence.
- Keep Provider, report-sink, and Reconciler authority boundaries explicit.

## Non-Goals

- Guarantee delivery or completion of an individual drift repair across a Control
  restart.
- Add a drift event ledger, durable repair queue, or durable repair claim.
- Treat drift as a Runtime lifecycle transition or terminal failure.
- Add another Provider protocol fallback or mixed-version mode.

## Requirements

### REQ-1. Truthful Provider observation

Providers must report backend lifecycle facts without using command history,
repair state, or NetworkPolicy drift to rewrite lifecycle.

**Acceptance criteria**

- A healthy ready Pod reports `running` through Provider restart and reconnect.
- NetworkPolicy drift is reported independently from lifecycle.
- Provider observation remains read-only.

### REQ-2. Bounded drift repair

Control must issue one supported non-destructive repair when a current periodic
observation reports supported drift, and it must rely on a later periodic
observation after observation, dispatch, or process loss.

**Acceptance criteria**

- A current `network_policy:drifted` observation from `OBSERVE` can cause one
  `UPDATE_CONFIGURATION` dispatch.
- A failed, lost, or interrupted repair is retried only after later periodic
  observation.
- No durable Runtime row stores drift status, repair claim, or repair retry time.

### REQ-3. Current authority fences

Only the current Provider connection and exact current Runtime configuration may
authorize a repair dispatch.

**Acceptance criteria**

- Stale Provider generation, Runtime desired generation, or configuration revision
  cannot dispatch repair.
- Pending configuration adoption, lifecycle work, reset, and terminal deletion
  retain their existing precedence.

### REQ-4. Explicit role boundaries

The Provider, Runtime Control report sink, and Reconciler must have documented
non-overlapping responsibilities and prohibitions.

**Acceptance criteria**

- Provider has no lifecycle reinterpretation, repair selection, or durable state
  authority.
- Report sink validates and projects reports but does not retain drift or invent
  lifecycle actions.
- Reconciler selects commands from durable desired state and current observation
  handoff, but does not reconstruct backend facts or Provider policy.

## Fixed Constraints

- `OBSERVE` remains read-only.
- `UPDATE_CONFIGURATION` remains the existing non-destructive NetworkPolicy
  application boundary.
- Existing periodic observation and Provider command routing remain the retry
  mechanism.
- Kubernetes Provider v2-only registration remains required.
- No live infrastructure action or PR merge is part of this work.

## Open Assumptions

- The existing periodic reconcile interval is an acceptable bounded retry delay
  after a lost observation or repair dispatch.

## Confirmation

Confirmed by the requester on 2026-08-05 through the instruction to implement
immediate repair with next-tick re-observation and to proceed without further
questions.
