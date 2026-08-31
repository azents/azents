---
title: "Clear and Reliable Runtime Lifecycle"
created: 2026-08-25
tags: [runtime, lifecycle, provider, runner, frontend, reliability, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260825
---

# runtime-260825/ADR: Clear and Reliable Runtime Lifecycle

## Context

The confirmed
[runtime-260825/REQ](../requirements/runtime-260825-reliable-lifecycle.md)
requires one predictable Runtime lifecycle contract across Control, Kubernetes and
Docker Providers, Runner connectivity, configuration convergence, Restart,
Recreation, Reset, permanent removal, and user-facing status.

The current implementation already has the required durable authority:

- PostgreSQL `agent_runtimes` desired and observed lifecycle fields;
- one bounded desired/applied Runtime configuration row;
- Provider and Runner connection generations;
- generation-fenced Provider reports and Runner registrations;
- explicit Reset and terminal-removal paths; and
- durable Runtime Recreation operations and items.

The remaining gaps are not a missing lifecycle database. They are inconsistent
composition of existing facts, Provider-local Restart replacement, Recreation
completion that does not require full availability, and UI surfaces that do not
show the same authoritative axes.

## Decision Map

### Fixed or derived outcomes

- PostgreSQL remains the durable lifecycle and operation authority.
- Provider resource facts and Runner facts remain separate.
- Configuration acknowledgement remains exact-sequence, digest, and generation
  fenced.
- Start, Stop, Restart, Recreation, and recovery preserve Agent Workspace data.
- Reset and terminal removal retain their separate destructive boundaries.
- Provider or Profile loss does not infer resource absence or select fallback
  authority.
- No permanent command or observation history is added.

### Accepted material decisions

- D1: publish one server-computed lifecycle presentation from existing durable
  axes.
- D2: normalize Restart into bounded deletion followed by ordinary Start
  convergence.
- D3: make Recreation reuse the same Restart handoff and hold concurrency until
  exact availability returns.
- D4: retain current-observation recovery and generation fencing as the only
  reconnect/failover authority.
- D5: keep destructive operations outside ordinary recovery and replacement.
- D6: perform one coordinated application/provider/frontend cutover without a
  compatibility lifecycle mode.

### Agent-owned implementation details

Field names below the documented public concepts, helper and module boundaries,
equivalent local typed structures, query composition, fixture names, and component
layout are implementation-owned when they do not add another state, authority,
mode, or fallback.

## Decisions

### runtime-260825/ADR-D1: Publish one composed lifecycle presentation

**Affected requirements:** `runtime-260825/REQ-1`, `REQ-2`, `REQ-3`, `REQ-6`,
`REQ-7`, `REQ-9`

Control composes one server-authoritative lifecycle presentation from:

- desired running or stopped target;
- convergence direction;
- Provider connection and resource observation;
- Runner state;
- current configuration status;
- terminal-removal state; and
- current-generation failure.

The presentation keeps Provider resource and Runner state as separate facts and
derives overall availability without requiring frontend recomposition. Public
Runtime settings and Workspace surfaces consume the same presentation semantics.
Raw Runtime fields remain diagnostic evidence, not a second UI authority.

The presentation is computed from current rows and does not create a new persisted
read model, cache, or event history.

**Rejected alternatives:**

- Frontend composition from raw Provider and Runner fields was rejected because
  separate surfaces can assign different meaning to the same evidence.
- Persisting a second lifecycle summary was rejected because it can drift from the
  authoritative axes and requires another repair path.
- Collapsing Runner readiness into Provider running was rejected because a running
  Pod or container can exist without a usable Runner.

### runtime-260825/ADR-D2: Hand Restart from deletion to ordinary Start

**Affected requirements:** `runtime-260825/REQ-1`, `REQ-3`, `REQ-4`, `REQ-8`,
`REQ-9`

An accepted Restart advances the Runtime desired generation while retaining the
running desired target and exact desired configuration. The Provider Restart
command validates ownership and issues deletion of Provider-owned execution
resources while preserving Agent Workspace storage. It does not recreate compute
or wait for resource absence, readiness, or Runner reconnection.

A successful correlated Restart completion atomically changes the current
generation's pending lifecycle command to Start and rearms lifecycle dispatch for
that same generation. Ordinary Start reconciliation then recreates the execution
environment. The user-visible Restart submission is complete at the deletion
request boundary; subsequent status is ordinary starting convergence.

The handoff is accepted only when Runtime ID, Provider identity and generation,
desired generation, command type, and successful correlated completion remain
current.

**Rejected alternatives:**

- Provider-local delete-and-create Restart was rejected because it creates a
  separate convergence loop, extends command duration through readiness, and
  duplicates Start recovery.
- Advancing a second desired generation for Start was rejected because it would
  split one explicit Restart into two user-visible authorities and complicate
  Recreation fencing.
- Persisting a long-lived `restarting` desired state was rejected because the final
  target remains running and existing Provider observations already express
  stopping and starting progress.

### runtime-260825/ADR-D3: Bind Recreation concurrency to full return to service

**Affected requirements:** `runtime-260825/REQ-3`, `REQ-5`, `REQ-6`, `REQ-9`

Runtime Recreation retains its exact target version and stable item set. Each item
dispatches the same Restart command and follows D2. A running item succeeds only
after all of the following match its exact dispatched target:

- desired and applied configuration sequence, digest, and generation;
- Provider resource observed running at the dispatched generation;
- current Provider connection; and
- Runner ready at the current generation with an authoritative Workspace path.

Until then, the item continues occupying one concurrency slot. Supersession,
stopped target, terminal removal, deleted target, changed configuration, and
current-generation failure retain explicit skipped, retry, or failed outcomes.

**Rejected alternatives:**

- Completing an item after Restart dispatch was rejected because concurrency would
  bound command submission rather than disruption.
- Completing after configuration application alone was rejected because a Runtime
  can have matching metadata while its Provider resource or Runner is unavailable.
- Creating a second Provider-specific recreation command was rejected because it
  would diverge from the user-visible Restart contract.

### runtime-260825/ADR-D4: Recover only from current fenced observation

**Affected requirements:** `runtime-260825/REQ-3`, `REQ-6`, `REQ-7`, `REQ-9`

Provider reconnect, leadership change, watch continuity loss, and Control restart
continue recovering through complete current observation and idempotent
reconciliation. Provider and Runner connection generations fence replaced streams.
Resource identity, desired generation, and exact configuration evidence fence
reports and acknowledgements.

Disconnected or unknown observation preserves the latest durable facts and closes
new mutation authority where current connectivity is required. It does not infer
resource or Workspace absence. Once current connectivity and observation return,
the ordinary lifecycle reconciler resumes the desired target.

**Rejected alternatives:**

- Clearing durable observations on disconnect was rejected because connection loss
  is not proof of backend absence.
- Trusting process-local watch or command history after failover was rejected
  because it is not durable and cannot prove current ownership.
- Retargeting delayed work to the latest generation was rejected because it would
  let stale commands mutate a replacement Runtime incarnation.

### runtime-260825/ADR-D5: Preserve explicit destructive boundaries

**Affected requirements:** `runtime-260825/REQ-4`, `REQ-5`, `REQ-7`, `REQ-8`,
`REQ-9`

Restart and Recreation delete only Provider-owned execution resources and preserve
the Agent Workspace storage boundary. Reset remains the only ordinary lifecycle
operation allowed to discard Agent Workspace data and retains its explicit final
desired state. Permanent removal retains its separate product cleanup, terminal
delete, and authoritative absence-verification workflow.

Automatic reconciliation, reconnect recovery, configuration adoption, Restart,
and Recreation never invoke Reset or permanent removal as fallback.

**Rejected alternatives:**

- Escalating failed Restart to Reset was rejected because it silently destroys
  user data.
- Reusing terminal removal for ordinary replacement was rejected because removal
  revokes Runtime capability and product state beyond execution resources.
- Allowing Provider-specific destructive Restart behavior was rejected because it
  changes the product contract by deployment backend.

### runtime-260825/ADR-D6: Use one coordinated lifecycle cutover

**Affected requirements:** `runtime-260825/REQ-2`, `REQ-3`, `REQ-7`, `REQ-9`

Backend, current Provider images, generated clients, and frontend lifecycle
presentation change in one coordinated release. There is one Control
interpretation of Restart completion and one server lifecycle presentation.

No feature flag, legacy summary fallback, Provider-specific frontend branch, or
dual-write lifecycle projection is introduced. The existing wire message can carry
the required correlated command completion and report, so this change does not add
a protocol field or persistence migration. An older Provider's idempotent
delete-and-create Restart completion is still normalized by the same Control
handoff rather than creating a second product mode; deployment nevertheless
updates both supported Provider images with the bounded deletion behavior.

**Rejected alternatives:**

- A frontend feature flag was rejected because it would retain two lifecycle
  meanings.
- A second persisted projection during rollout was rejected because it creates
  dual authority.
- A wire-version bump without a wire-contract change was rejected because current
  correlated completion already supplies all fencing inputs and Control applies
  one interpretation independent of Provider-local implementation.

## Consequences

- Runtime status becomes explainable as target, convergence, Provider resource,
  Runner, configuration, and availability instead of one overloaded label.
- Restart command duration no longer includes backend recreation or Runner
  readiness.
- Normal Start idempotency becomes the sole recreation mechanism after explicit
  Restart.
- Recreation concurrency measures disrupted Runtimes rather than submitted
  commands.
- No new database table, enum, migration, Redis correctness dependency, or event
  history is required.
- API clients and UI must be regenerated and updated in the same release.
- Provider tests must prove Restart does not recreate compute and preserves
  Workspace storage.

## Risks

- A lost successful Restart completion leaves the same command eligible for a
  bounded retry, which can issue duplicate deletion requests. Provider deletion
  must therefore remain idempotent.
- Kubernetes resources may remain terminating after Restart completion. Start
  reconciliation must tolerate existing terminating resources and retry until
  creation is possible.
- Holding Recreation slots until Runner readiness can make operations visibly
  longer, but it matches actual disruption and exposes failure instead of
  overstating success.
