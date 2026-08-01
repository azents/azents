---
title: "Workspace-Owned Runtime Profiles"
created: 2026-07-30
updated: 2026-07-31
tags: [runtime, provider, workspace, profile, infrastructure, security, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260730
---

# Workspace-Owned Runtime Profiles

- Snapshot: `runtime-260730`
- Document reference: `runtime-260730/ADR`
- Requirements: [Workspace-Owned Runtime Profiles Requirements](../requirements/runtime-260730-workspace-owned-runtime-profiles.md) (`runtime-260730/REQ`)

## Context

The current Runtime execution model distributes authority across global Profiles, Workspace and
Agent restrictions, Provider capability and configuration revisions, Provider selection, and
immutable Runtime policy snapshots. Resource, storage, Docker, and network settings are repeated as
ceilings or restrictive overlays, while a global Profile attempts to represent both customer-facing
execution choices and infrastructure owned by different Provider instances.

The replacement model must make customer choices Workspace-owned, keep Platform infrastructure
safety under the exact Provider that operates it, eliminate Agent infrastructure overrides, and
make configuration propagation authoritative without treating physical Runtime recreation as a
lower-level approval step.

## Decisions

### runtime-260730/ADR-D1: Make Runtime Profiles Workspace-owned complete Agent choices

**Affected requirements:** `runtime-260730/REQ-1`, `REQ-2`, `REQ-6`, `REQ-9`, `REQ-10`, `REQ-23`

A customer-facing Runtime Profile belongs to exactly one Workspace. It is not global, inherited, or
an overlay of another Runtime Profile. An Agent selects one Runtime Profile owned by its Workspace
and has no independent CPU, memory, storage, Docker, network, Provider, or infrastructure Profile
overrides.

A Workspace may designate an optional default Runtime Profile. The default is copied as the Agent's
exact selection only when an Agent is created without an explicit selection. Changing the Workspace
default affects future Agents only. An Agent may exist without a selected Runtime Profile, but it
cannot provision or recreate a Runtime until a valid selection is stored.

**Rationale:**

- One stored selection makes the Agent execution environment explainable without reconstructing an
  inherited restriction hierarchy.
- Workspace ownership gives customer administrators a local catalog without pretending that one
  infrastructure choice is globally portable.
- Creation-time defaulting provides convenience without making existing Agents dynamically follow a
  mutable Workspace default.

**Rejected alternatives:**

- Global customer-facing Profiles were rejected because Provider-specific infrastructure cannot be
  represented truthfully as one portable resource.
- Agent resource and network overrides were rejected because they recreate the hierarchy and
  effective-policy merge problem.
- A dynamically inherited Workspace default was rejected because changing the default would
  silently move existing Agents to another execution environment.

### runtime-260730/ADR-D2: Separate Provider-owned infrastructure Profiles from Workspace Runtime Profiles

**Affected requirements:** `runtime-260730/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`, `REQ-19`

A Platform-owned Provider owns infrastructure Profiles scoped to that exact Provider instance. A
Kubernetes Provider owns Pod Profiles, and a Docker Provider owns Container Profiles. A Workspace
Runtime Profile using a Platform Provider binds one exact Provider and one infrastructure Profile
owned by that Provider. Failure or incompatibility never substitutes another Provider or Profile.

Platform-owned infrastructure Profiles define the non-weakenable infrastructure preset. A
Workspace Runtime Profile may add Workspace-owned restrictions, initially including network
restrictions, but cannot replace or weaken Platform-owned identity, security, storage, resource, or
network boundaries.

For a future Workspace-owned Provider, infrastructure authority may move into the owning
Workspace's Runtime Profiles because that Workspace owns the infrastructure risk and cost. Provider
ownership, rather than Provider kind alone, determines the configuration authority.

**Rationale:**

- Infrastructure policy belongs with the actor operating and paying for the underlying substrate.
- Provider-instance ownership prevents two Kubernetes clusters or Docker hosts from pretending to
  offer interchangeable Profiles.
- Exact binding preserves deterministic provisioning and failure behavior.

**Rejected alternatives:**

- Provider-neutral global infrastructure Profiles were rejected because they hide differences in
  storage, security, scheduling, networking, and implementation capability.
- A fallback Provider or infrastructure Profile was rejected because it silently changes cost,
  security, persistence, and execution behavior.

### runtime-260730/ADR-D3: Treat authenticated Provider capability advertisements as authoritative

**Affected requirements:** `runtime-260730/REQ-15`, `REQ-16`, `REQ-17`, `REQ-18`

After Provider authentication and identity binding, Runtime Control validates the advertised
capability payload for schema, identity, protocol, and supported contract semantics. A valid
advertisement immediately becomes the Provider's authoritative current capability state. There is
no candidate, Admin acceptance, Apply, or previously accepted capability pointer.

Capability advertisements describe technical compatibility and do not grant infrastructure
authority beyond the authenticated Provider's existing ownership and execution boundary. Immutable
revision history may be retained for audit, impact analysis, and diagnostics, but a historical
revision cannot be pinned or reactivated as downstream authority.

**Rationale:**

- A Provider already has infrastructure and Runtime lifecycle authority; Admin acceptance of the
  Provider's self-declared JSON does not verify the implementation.
- Removing accepted-versus-current state prevents stale capability drift and deployment approval
  delays.
- Real security boundaries remain Provider enrollment, credentials, infrastructure authorization,
  typed Profile schemas, and non-weakenable Platform policy.

**Rejected alternatives:**

- Manual Admin acceptance was rejected because it adds operational latency without proving that the
  Provider implements its declaration.
- Retaining the previous accepted capability during a changed advertisement was rejected because it
  lets the control plane reason from a state the connected Provider no longer claims.

### runtime-260730/ADR-D4: Preserve references and running incarnations when capability is lost

**Affected requirements:** `runtime-260730/REQ-11`, `REQ-12`, `REQ-16`

When a Provider removes a capability required by an infrastructure Profile, the current capability
state remains authoritative. The infrastructure Profile is preserved but becomes incompatible or
blocked. Dependent Workspace Runtime Profiles retain their exact references but become unavailable,
and existing Agent selections remain attached without fallback.

An already-running physical Runtime may continue using its last applied configuration. Operations
that require a new physical incarnation, including creation, start, restart, reset, and recreation,
are blocked until compatibility is restored. Stop and terminal delete remain available. Restoring
the capability automatically reevaluates and unblocks preserved references without Admin or Agent
approval.

**Rationale:**

- Capability loss does not prove that already-created infrastructure has disappeared or become
  unsafe, so automatic termination would create avoidable outages.
- Preserving references makes impact visible and allows automatic recovery.
- Blocking new incarnations prevents the system from provisioning against a capability the Provider
  no longer advertises.

**Rejected alternatives:**

- Immediate Runtime termination was rejected because a Provider restart, rollback, or advertisement
  error could cause fleet-wide interruption.
- Automatic fallback was rejected because it changes infrastructure authority and execution
  behavior.
- Historical capability pinning was rejected because it violates authoritative propagation.

### runtime-260730/ADR-D5: Use compatibility-bound typed Profile contracts

**Affected requirements:** `runtime-260730/REQ-17`, `REQ-18`, `REQ-19`, `REQ-20`

Infrastructure Profile contracts use versions only for backward-incompatible interpretation
boundaries. Additive optional fields, capabilities, values, or independent modules remain within the
same contract version when existing valid Profiles retain their meaning. Providers advertise the
contract versions, modules, and constrained values they support; an unsupported requirement blocks
compatibility instead of being silently ignored.

Infrastructure Profiles contain only typed Azents-defined modules. Raw Kubernetes PodSpec, YAML,
container and volume fragments, Docker create options, host mounts, daemon arguments, and equivalent
escape hatches are prohibited. Pod Profiles and Container Profiles remain distinct resources while
reusing common semantic modules where the observable product meaning is equivalent. Provider-kind
specific modules retain substrate-native precision.

**Rationale:**

- Compatibility-bound versions avoid version churn for every additive feature.
- Capability negotiation lets older Providers remain compatible with Profiles that do not use a new
  feature.
- Typed modules make ownership, omission, validation, security, and recreation impact explicit.

**Rejected alternatives:**

- Feature-release versioning was rejected because it turns every additive capability into a
  migration event.
- A single universal Infrastructure Profile schema was rejected because it erases Kubernetes and
  Docker differences.
- Arbitrary native configuration was rejected because the control plane could not validate security
  or compatibility and lower scopes could bypass Platform boundaries.

### runtime-260730/ADR-D6: Propagate authoritative desired configuration without lower-level approval

**Affected requirements:** `runtime-260730/REQ-11`, `REQ-12`, `REQ-13`, `REQ-14`

A Provider infrastructure Profile or Workspace Runtime Profile change immediately updates the
latest desired configuration of every dependent Runtime. Agents and lower-level administrators
cannot reject the change, retain an older parent version, or require an Apply action.

Physical Runtime adoption may remain deferred until recreation. Desired state and last applied
incarnation evidence are stored separately so this condition is represented as waiting for
recreation, not waiting for approval. Starting or recreating a Runtime always uses the latest
resolvable desired configuration.

A Platform Admin can trigger bounded recreation for Runtimes governed by a Platform Provider or
infrastructure Profile. A Workspace Admin can trigger bounded recreation for Runtimes selecting one
Workspace Runtime Profile. Future deadlines, maintenance windows, and staged rollout may control
when recreation occurs but cannot restore downstream veto or version pinning.

**Rationale:**

- Configuration ownership is meaningful only if lower scopes cannot retain obsolete parent policy.
- Separating desired from applied state acknowledges physical replacement without reintroducing an
  approval workflow.
- Scope-owned bulk recreation gives each authority an operational mechanism to converge its changes.

**Rejected alternatives:**

- Direction-sensitive automatic restriction and explicit expansion Apply were rejected because both
  keep a second lower-level authority over parent configuration.
- Updating only newly created logical Runtimes was rejected because existing dependencies would
  remain permanently stale.

### runtime-260730/ADR-D7: Keep DinD activation and Kubernetes boundaries in Provider-owned Pod Profiles

**Affected requirements:** `runtime-260730/REQ-5`, `REQ-8`, `REQ-19`, `REQ-20`, `REQ-21`, `REQ-22`

A Provider capability advertisement declares whether the implementation supports a DinD topology.
For a Platform Kubernetes Provider, a Pod Profile decides whether DinD is present and owns the
Runner and Docker engine CPU and memory requests and limits, Docker storage topology, socket
connection, and required security implementation. A Workspace Runtime Profile does not contain an
independent DinD toggle; it selects a Pod Profile that already includes or excludes DinD.

Kubernetes Pod component CPU and memory request and limit fields are either explicit quantities or
an explicit choice to omit the Kubernetes field. Omission does not inherit a Provider default or
another Profile. Arbitrary component names are prohibited.

The existing Workspace PVC shape and lifecycle are preserved: one dedicated `ReadWriteOnce` PVC per
logical Runtime, preservation across stop, start, restart, and ordinary recreation, deletion and
recreation on reset, and deletion on terminal delete. The source of existing configurable values may
move into the Pod Profile without otherwise changing Volume semantics.

Kubernetes network policy retains three authority boundaries: a Provider-wide hard boundary, the
selected Pod Profile's Platform policy, and additional Workspace restrictions. Lower boundaries can
only narrow customer traffic. Mandatory Runtime Control and Provider-required communication remains
separately protected.

**Rationale:**

- DinD is an infrastructure topology and privileged security decision, not an Agent preference.
- Explicit component resources make the Platform preset complete without hidden defaults.
- Preserving Workspace PVC behavior prevents authoritative recreation from becoming unexpected data
  destruction.
- A Provider-wide network hard boundary limits damage from a misconfigured Pod Profile.

**Rejected alternatives:**

- A Workspace-level DinD toggle for Platform Providers was rejected because it splits topology,
  resource, storage, and security ownership across layers.
- Ephemeral Workspace storage was rejected for this snapshot because Platform-triggered recreation
  must not destroy ordinary Agent workspace data.
- Moving the entire Provider network hard boundary into each Pod Profile was rejected because one
  Profile could accidentally exceed the Provider's installation-wide safety boundary.

### runtime-260730/ADR-D8: Derive Docker Profiles from the same authority and lifecycle model

**Affected requirements:** `runtime-260730/REQ-4`, `REQ-5`, `REQ-8`, `REQ-18`, `REQ-19`

Docker Container Profiles follow the same ownership, typed-module, capability compatibility,
propagation, blocked-state, desired-versus-applied, and recreation semantics as Kubernetes Pod
Profiles. Their concrete fields and implementation remain Docker-native and are not forced to copy
Kubernetes concepts that have no equivalent.

Common semantic modules may be reused where their observable behavior is equivalent. Docker-specific
resource, network, storage, security, and engine-access configuration remains in typed Docker
modules owned by the exact Docker Provider.

**Rationale:**

- Shared product semantics prevent Provider kinds from inventing conflicting lifecycle behavior.
- Substrate-native realization avoids a misleading lowest-common-denominator Profile schema.

**Rejected alternatives:**

- Requiring Docker to expose Kubernetes request, ServiceAccount, scheduling, or Pod security
  concepts was rejected because semantic reuse does not require identical infrastructure fields.

### runtime-260730/ADR-D9: Complete a one-way replacement of legacy Runtime policy authority

**Affected requirements:** `runtime-260730/REQ-1`, `REQ-6`, `REQ-9`, `REQ-11`, `REQ-12`, `REQ-15`,
`REQ-16`, `REQ-23`

The Workspace-owned Runtime Profile model becomes the sole production authority for Agent
selection, Runtime configuration resolution, desired state, applied evidence, compatibility, and
lifecycle eligibility. The cutover converts legacy effective data once and then removes active
legacy execution-policy parsers, application services, repositories, permissions, capability
branches, Agent Provider overrides, and Runtime policy snapshots. Migration code may retain the
historical resolver needed to interpret old rows, but runtime requests, workers, status projection,
and Provider Control do not read or fall back to those rows after conversion.

Provider-global operational configuration revisions remain a separate supported mechanism for
controller credentials, namespaces, implementation images, endpoints, and equivalent
Provider-owned process configuration. They cannot carry customer Runtime resource, storage,
network, Docker, or Profile-selection authority that this snapshot assigns to infrastructure and
Workspace Runtime Profiles.

The replacement stack must project both desired and applied Runtime state into the new revision
model before deleting obsolete persistence. Unknown or unverifiable historical applied evidence is
represented explicitly in the new model and never recovered through a legacy status path. Removal
of the superseded production authority is part of the replacement phases and cannot be deferred to
the final documentation cleanup phase.

**Rationale:**

- Keeping both resolvers creates two sources of truth that can disagree about whether a Runtime is
  configured, applicable, or safe to start.
- A migration-only interpreter preserves historical conversion without making legacy semantics a
  permanent compatibility contract.
- Separating Provider operational configuration from customer Runtime configuration preserves
  legitimate Provider management without restoring the superseded policy hierarchy.

**Rejected alternatives:**

- A permanent legacy read fallback was rejected because it makes cutover completeness dependent on
  which caller or status surface is used.
- Retaining legacy services and tables as dormant compatibility infrastructure was rejected because
  internal callers and tests would continue to preserve obsolete authority.
- Removing all Provider configuration revisions was rejected because Provider-owned operational
  configuration is distinct from Runtime Profile authority.

### runtime-260730/ADR-D10: Require exact two-party adoption evidence and snapshot-fenced recreation

**Affected requirements:** `runtime-260730/REQ-11`, `REQ-12`, `REQ-13`, `REQ-14`, `REQ-16`,
`REQ-21`, `REQ-22`

Applied Runtime configuration advances only after the Provider reports the exact ready revision,
digest, and desired generation and the Runner subsequently reports the same evidence through its
ordinary state-report path. Runtime Control may include pending exact evidence in the Runner
heartbeat acknowledgement only after the Provider acknowledgement is durable. The Runner adopts
that evidence only within its current desired generation and immediately emits an ordinary state
report. There is no dedicated configuration-update request, acknowledgement, relay, or independent
completion authority.

A scoped recreation operation snapshots both the affected Runtime identities and each Runtime's
expected desired revision under the target's optimistic version fence. A worker locks one exact
running item attempt with PostgreSQL `FOR UPDATE SKIP LOCKED`, dispatches at most one atomic
generation-fenced restart, and durably records the resulting revision and generation. Success
requires that exact dispatched revision to become applied.

The operation never refreshes an item to an unrelated later desired revision. A target change
before dispatch is skipped as a changed snapshot target. A later command that supersedes an exact
dispatch is skipped rather than causing an implicit second restart. An exact failed dispatch may
retry only within the bounded durable attempt count. A new authoritative target version requires a
new recreation operation.

**Rationale:**

- Provider evidence proves substrate adoption, while Runner evidence proves the running process
  received the same configuration; neither alone is sufficient.
- Reusing heartbeat delivery and ordinary state reports avoids a second applied-state machine.
- Stable target snapshots make progress and failures explainable and prevent one operation from
  silently expanding to later configuration changes.
- Transaction-held item locks and exact dispatch evidence prevent peer workers from duplicating a
  restart or losing the durable record of an already-issued generation.

**Rejected alternatives:**

- A dedicated Runner configuration-update operation was rejected because it duplicates delivery,
  acknowledgement, generation fencing, and applied promotion already owned by Runner Control and
  state reports.
- Refreshing each item to the newest desired revision during worker execution was rejected because
  one version-fenced operation could then apply a target the initiating administrator did not
  inspect.
- Polling RUNNING items without a transaction-held item lock was rejected because concurrent
  workers could race dispatch recording and retry transitions around one physical restart.

## Superseded Decisions

This snapshot fully supersedes `provider-260722/ADR-D4`, which required Admin acceptance of
Provider-proposed Capability Contracts. It narrows `provider-260722/ADR-D5` so the exact Provider
binding is selected through a Workspace Runtime Profile rather than an independent Agent or Platform
default, while retaining durable exact binding. It supersedes the portions of
`provider-260722/ADR-D6` that treat customer Runtime policy as an accepted Provider configuration
snapshot; Provider-global operational configuration may remain independently revisioned where it is
not replaced by infrastructure Profiles.

This snapshot supersedes the Platform/Workspace/Profile/Agent execution-policy hierarchy,
direction-sensitive Apply behavior, resource-ceiling merge, and reserved global Standard Profile
identity in `runtime-260726/ADR-D1` through `ADR-D6` and `ADR-D10`, and in
`runtime-260727/ADR-D1` through `ADR-D3`. Immutable desired-versus-applied evidence and exact
Provider application evidence remain valid only where consistent with authoritative downward
propagation in this ADR.

This snapshot supersedes the Profile ownership and configuration-source portions of
`docker-260728/ADR-D4` and replaces the unreleased contract-version strategy in
`docker-260728/ADR-D6` with compatibility-bound versioning. Direct Docker authority and the
requirement that safer isolation use a distinct enforceable implementation remain valid where not
contradicted by Provider-owned Container Profiles.

## Consequences

- Existing global Runtime execution Profiles, Workspace and Agent restriction records, independent
  Agent Provider preferences, Provider contract acceptance state, and immutable one-time Runtime
  policy binding no longer match the target product model.
- The Runtime domain requires authoritative desired configuration references plus separate applied
  incarnation evidence and dependency projections for Provider, infrastructure Profile, Workspace
  Runtime Profile, and Agent selection.
- Provider capability changes require automatic compatibility and impact reconciliation rather than
  an Admin review queue.
- Admin and Workspace management surfaces require separate Provider infrastructure Profile and
  Workspace Runtime Profile workflows.
- Runtime recreation becomes an explicit scoped operation with bounded progress and failure
  reporting.
- The implementation may use a one-way migration because compatibility with the unreleased legacy
  hierarchy is not a product requirement for this snapshot.
