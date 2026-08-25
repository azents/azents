---
title: "Clear and Reliable Runtime Lifecycle Requirements"
created: 2026-08-25
updated: 2026-08-25
implemented: 2026-08-25
tags: [runtime, lifecycle, provider, runner, frontend, reliability]
document_role: primary
document_type: requirements
snapshot_id: runtime-260825
---

# Clear and Reliable Runtime Lifecycle Requirements

- Snapshot: `runtime-260825`
- Document reference: `runtime-260825/REQ`

## Problem

Agent Runtime lifecycle behavior is currently difficult to reason about across
desired lifecycle state, Provider-managed resources, Runner availability,
configuration adoption, reconnects, failover, Restart, and batch recreation.
Users can see an apparently running Runtime while its Runner is unavailable, or
see raw technical state without understanding whether the Runtime is starting,
stopping, blocked, disconnected, or ready for use.

The lifecycle must converge safely through partial failure while presenting one
clear, truthful, and actionable user experience.

## Primary Actor

An authorized Workspace user or Agent administrator who starts, stops, monitors,
or otherwise manages an Agent Runtime.

## Primary Scenario

The actor changes an Agent Runtime's lifecycle target between running and stopped.
The product immediately shows the direction of convergence, separately shows the
Provider-managed Runtime resource and Runner state, prevents unavailable
operations, and continues reconciling until the requested target is satisfied or
a clear failure or blocked condition is shown. Control, Provider, Runner, or
network reconnection must not allow an older command or observation to replace the
current state.

## Supporting Scenarios

- The actor confirms Restart for a running Runtime while preserving Agent
  Workspace storage.
- A System Administrator or Workspace-authorized actor recreates multiple
  Runtimes after an exact Provider or Runtime Profile change and monitors bounded
  rollout progress.
- The Provider reconnects, fails over, or rebuilds its observation state while
  Runtime resources continue to exist.
- A Runtime Pod or container is running while the Runner is not ready or
  disconnected.
- Current configuration is blocked, requires in-place application, or requires
  explicit recreation.
- An administrator resets or permanently removes a Runtime through a distinct
  destructive workflow.

## Goals

- Make running and stopped lifecycle targets converge predictably and safely.
- Keep Provider resource facts, Runner facts, configuration state, and overall
  availability understandable and distinct.
- Make Restart and Recreation reuse the normal lifecycle convergence model
  without creating confusing long-lived restart state.
- Prevent stale connections, commands, reports, and resource observations from
  becoming current authority.
- Preserve Agent Workspace data across ordinary Start, Stop, Restart, and
  Recreation.
- Give users clear actions, transition feedback, failures, and recovery guidance.

## Non-Goals

- Changing whether an Agent has managed Runtime capability or how a Runtime
  Profile is selected.
- Introducing Session-specific or subagent-specific lifecycle authority.
- Retaining permanent command, configuration, or resource-observation history as
  product state.
- Automatically performing a destructive recreation when policy requires explicit
  user or administrator authorization.
- Treating Provider resource readiness and Runner readiness as one factual state.
- Providing a compatibility or fallback mode that preserves obsolete lifecycle
  authority alongside the new behavior.

## Requirements

### REQ-1. Authoritative lifecycle target

The product must maintain one current running or stopped lifecycle target for each
managed Runtime and converge the Provider-managed execution environment toward it.

**Acceptance criteria**

- Start changes the target to running and Stop changes it to stopped.
- Repeating Start or Stop is safe and does not create a second user-visible
  lifecycle operation.
- A running target eventually creates or restores missing required execution
  resources when the Provider is available.
- A stopped target removes ordinary execution resources while preserving Agent
  Workspace storage.
- A current terminal-removal workflow takes precedence over ordinary lifecycle
  convergence.

### REQ-2. Truthful and unambiguous Runtime UI

The product must show lifecycle progress and availability without requiring users
to interpret raw Provider or Runner fields.

**Acceptance criteria**

- The UI distinguishes at least starting, running, stopping, stopped, failed,
  Provider-disconnected, and Runner-unavailable outcomes where applicable.
- Runtime resource state and Runner state are shown as separate facts.
- Overall Runtime availability is shown separately and is ready only when the
  required resource and Runner conditions are satisfied.
- The UI shows the direction of convergence when desired and observed state
  differ.
- Actions that cannot currently succeed are disabled or rejected with a clear
  reason and recovery guidance.
- Desktop and mobile surfaces use the same server-authoritative lifecycle and
  availability meaning.

### REQ-3. Stale-result safety

Reconnects, failover, delayed reports, duplicate work, and replaced Runtime
resources must not allow stale results to overwrite current lifecycle,
configuration, or availability.

**Acceptance criteria**

- A replaced Provider or Runner connection cannot mutate current state.
- A report from a replaced Runtime resource cannot become the current resource
  observation.
- A delayed command result is associated only with the command that produced it.
- A configuration acknowledgement is accepted only for the exact current
  configuration identity.
- Repeated reconciliation attempts are safe.

### REQ-4. Restart as a bounded explicit action

An authorized actor must be able to restart a running Runtime without changing its
running target or deleting Agent Workspace storage.

**Acceptance criteria**

- Restart requires explicit confirmation that the execution environment will be
  temporarily unavailable while Workspace data is preserved.
- Restart requests deletion of the current Provider-owned execution resources
  except the Workspace PVC/PV or equivalent durable Workspace storage.
- Restart completes when the Provider has issued the required deletion requests;
  it does not wait for deletion, recreation, Runtime readiness, or Runner
  reconnection.
- Normal running-target reconciliation recreates the required execution
  environment afterward.
- The UI stops showing Restart submission progress when the bounded Restart action
  completes and separately shows subsequent lifecycle convergence.
- A failed or uncertain Restart result is shown explicitly and may be safely
  retried.

### REQ-5. Bounded Runtime Recreation

Authorized Provider or Runtime Profile changes that require recreation must be
applicable to an exact set of affected Runtimes with bounded concurrency and clear
progress.

**Acceptance criteria**

- A recreation operation identifies one exact Provider or Profile target version
  and a stable target Runtime set.
- Each target Runtime uses the same user-visible Restart behavior rather than a
  second recreation-specific lifecycle behavior.
- The concurrency limit bounds Runtimes that have begun recreation but have not
  yet returned to the required current configuration and availability.
- Item and aggregate progress distinguish pending, running, succeeded, skipped,
  and failed outcomes.
- Stop, terminal removal, target deletion, target-version change, and current
  configuration change produce explicit bounded outcomes rather than hidden
  lifecycle work.
- Recreation preserves Agent Workspace storage.

### REQ-6. Exact configuration convergence

Lifecycle and availability must use only the current desired and applied Runtime
configuration evidence.

**Acceptance criteria**

- Configuration application distinguishes ready, blocked, in-place-applicable,
  and recreation-required outcomes.
- In-place-applicable changes do not recreate the Runtime resource.
- Recreation-required changes remain pending until explicitly authorized through
  Recreation or Restart where appropriate.
- Provider and Runner acknowledgements identify the exact current configuration
  sequence and digest.
- An older or overwritten configuration cannot become applied.
- Configuration failure or blockage is shown without rewriting Provider resource
  or Runner facts.

### REQ-7. Recovery through observation and reconciliation

The lifecycle must recover from missed events, process restart, Provider failover,
and temporary connection loss through current observation and idempotent
reconciliation.

**Acceptance criteria**

- Provider startup and watch recovery establish a current resource snapshot before
  command authority is treated as ready.
- Watch expiration or continuity loss triggers a complete authoritative
  re-observation.
- A temporarily disconnected Provider does not cause the product to infer that a
  Runtime or its Workspace is absent.
- Once current observation and connectivity return, the Runtime resumes
  convergence without manual database repair.
- Leadership uncertainty closes new mutation admission until authority is current
  again.

### REQ-8. Distinct destructive boundaries

Stop, Restart, Reset, and permanent Runtime removal must have distinct effects,
confirmation, progress, and completion meaning.

**Acceptance criteria**

- Stop and Restart preserve Agent Workspace storage.
- Restart preserves the running target; Stop changes it to stopped.
- Reset clearly states which Workspace data or execution state is destroyed and
  what final lifecycle target will remain.
- Permanent removal prevents new Runtime use, deletes the complete authorized
  Runtime and Workspace resource set, and does not report completion until absence
  is authoritatively verified.
- A less destructive action cannot be silently upgraded to Reset or permanent
  removal.

### REQ-9. Provider-consistent lifecycle contract

Kubernetes and Docker Providers must expose the same user-visible lifecycle
meaning while retaining Provider-specific resource implementation.

**Acceptance criteria**

- Start, Stop, Restart, configuration application, observation, failure, and
  recovery have the same product meaning across supported Providers.
- Provider-specific resource sets and readiness details do not change the
  user-visible action contract.
- Unsupported Provider capability is reported explicitly rather than emulated
  through a different lifecycle behavior.

## Fixed Constraints

- PostgreSQL remains authoritative for durable Runtime target, configuration,
  Recreation, and permanent-removal correctness.
- Redis and process-local state remain replaceable coordination state and cannot
  be required to prove Runtime or Workspace existence.
- Provider and Runner input is untrusted and must be authenticated and
  freshness-fenced before changing durable state.
- Agent Workspace storage is preserved across Start, Stop, Restart, and
  Recreation.
- Existing implemented Requirements, ADRs, and Designs remain immutable
  historical records.
- Protocol and persistence migration uses a coordinated current-version cutover;
  no legacy fallback or dual-authority product mode is retained.

## Open Assumptions

- Existing Runtime management and Workspace surfaces can present the required
  lifecycle, Runner, configuration, and availability projections without a new
  top-level product area.
- Supported Providers can implement idempotent creation and deletion at their
  owned-resource boundary.
- Recreation scale remains suitable for a bounded durable operation with item
  progress and configured concurrency.

## Confirmation

Confirmed by the requester on 2026-08-25 before ADR and design decisions began.
