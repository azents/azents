---
title: "Runtime Deployment Continuity"
created: 2026-08-04
tags: [runtime, backend, provider, reconciliation, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260804
---

# Runtime Deployment Continuity

- Snapshot: `runtime-260804`
- Document reference: `runtime-260804/ADR`
- Requirements: [Runtime Deployment Continuity Requirements](../requirements/runtime-260804-deployment-continuity.md) (`runtime-260804/REQ`)
- Decision mode: Autonomous
- Decision owner: `runtime-design-owner`

## Context

The Kubernetes Runtime Provider currently rewrites a healthy Pod observation to
`starting` when the current Provider process has not previously verified the
Runtime's NetworkPolicy through a matching command. The verification cache is
process-local and includes the Provider connection generation, so a Provider
deployment removes the cache and turns transport reconnection into a persisted
Runtime lifecycle transition.

The intended Runtime boundary is already fixed by `runtime-260804/REQ`: Providers
report backend facts and drift, Runtime Control owns durable desired state and
repair decisions, connection generations fence transport freshness, and automatic
recovery preserves Agent Workspace data.

## Decisions

### runtime-260804/ADR-D1: Carry optional kind-scoped reconciliation observations

**Affected requirements:** `runtime-260804/REQ-1`, `REQ-3`, `REQ-4`

`RuntimeProviderReport` adds one optional structured reconciliation-evidence
message. Message absence means that the report has no authoritative
reconciliation update. A present message contains kind-scoped observations, each
with a kind, `in_sync` or `drifted` status, a bounded reason, and bounded safe
diagnostics.

The initial actionable kind is `network_policy`. Its status describes only the
managed NetworkPolicy comparison and never means that the complete Runtime is
globally in sync. Reports reject empty kinds, duplicate kinds, invalid statuses,
and drift observations without a bounded reason. The protocol carries no
recommended lifecycle or configuration command.

**Rejected alternatives:**

- Overloading lifecycle state was rejected because drift is not a backend
  lifecycle transition.
- Using `reason` or `diagnostic` alone was rejected because those fields are not a
  durable typed control contract.
- A global `in_sync` status was rejected because the first implementation verifies
  only NetworkPolicy.
- A Provider-selected repair action was rejected because it would create a second
  lifecycle authority.

### runtime-260804/ADR-D2: Persist current recognized evidence on the Runtime

**Affected requirements:** `runtime-260804/REQ-3`, `REQ-4`, `REQ-5`

Runtime Control persists the latest recognized kind-scoped observation on the
Agent Runtime row. The durable projection contains status, kind, bounded reason,
Provider connection generation, desired generation, exact configuration revision
ID, observation time, and repair-request time.

Absence of durable evidence is distinct from an `in_sync` observation. A report
without structured evidence does not clear or replace the stored observation.
Evidence for another desired generation, Provider connection generation, or
configuration revision cannot authorize repair.

An atomic repair claim updates the repair-request time only while every evidence
fence still matches and the retry interval is eligible. This prevents concurrent
Runtime Control replicas from dispatching the same evidence repeatedly while
allowing bounded retry after route or command failure. Current evidence replaces
the earlier projection; no drift event ledger or historical replay authority is
introduced.

**Rejected alternatives:**

- Reusing Runtime configuration acknowledgement fields was rejected because they
  prove desired/applied revision adoption rather than arbitrary backend-resource
  drift.
- Reusing Runtime failure fields was rejected because expected drift is not a
  terminal Runtime failure and lifecycle-only reports must not clear it.
- A separate event table was rejected because this change needs only the latest
  generation-fenced repair input.
- Process-local or coordination-store-only evidence was rejected because Runtime
  Control restart must not lose current actionable drift.

### runtime-260804/ADR-D3: Limit authoritative evidence to command-scoped comparison

**Affected requirements:** `runtime-260804/REQ-1`, `REQ-3`, `REQ-5`

Only a Provider command execution that receives the complete canonical Runtime
configuration envelope may emit authoritative reconciliation observations.
Kubernetes explicit `observe`, `start`, and `update_configuration` results may
therefore report NetworkPolicy comparison evidence.

Pod watch and leader-failover scan reports continue reporting actual backend
lifecycle and configuration metadata but omit reconciliation evidence because
they do not possess the expected resolved Profile. They cannot clear newer
command-scoped evidence. Historical Provider-generation resource labels remain
command metadata; the Provider run loop continues replacing their value with the
current stream generation when framing the outgoing report.

**Rejected alternatives:**

- Reconstructing expected policy from Pod labels was rejected because labels
  describe applied metadata rather than the complete current expected Profile.
- Hydrating a new Provider process from the old command cache was rejected because
  command history is not durable observation authority.
- Adding a NetworkPolicy watch was rejected because periodic explicit observation
  already provides bounded drift detection and a second watch is unnecessary for
  this focused correction.

### runtime-260804/ADR-D4: Reconcile only an authoritative current configuration

**Affected requirements:** `runtime-260804/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`

Configuration adoption and explicit recreation retain precedence over periodic
drift repair. Authoritative NetworkPolicy evidence is actionable only when its
configuration revision is the Runtime's exact current desired and applied
revision.

When desired and applied revisions differ, Runtime Control follows the existing
configuration-adoption or explicit-recreation path and does not use observation to
apply or repair the pending revision. Periodic observation may continue reporting
lifecycle, but it does not create actionable NetworkPolicy evidence until the
revision boundary converges.

**Rejected alternatives:**

- Comparing a pending desired revision was rejected because observation could then
  authorize implicit adoption or recreation.
- Reusing an older applied envelope with the current desired generation was
  rejected because configuration revision evidence is generation-fenced and must
  not be rewritten.
- Adding a separate comparison-generation protocol was rejected as unnecessary
  scope for the deployment-continuity correction.

### runtime-260804/ADR-D5: Map current NetworkPolicy drift to in-place repair

**Affected requirements:** `runtime-260804/REQ-3`, `REQ-4`, `REQ-6`

Runtime Control maps a current exact `network_policy:drifted` observation to
`UPDATE_CONFIGURATION`. The Provider applies the already-authoritative
NetworkPolicy configuration and reports a fresh comparison result. An `in_sync`
result clears the drift projection for that kind.

Lifecycle dispatch and configuration adoption run before drift repair. Unknown,
absent, stale, or connection-generation-mismatched evidence triggers or waits for
a fresh read-only `OBSERVE`; it never implies `START`. Repair claims use the
existing bounded Provider command deadline and periodic retry cadence.

**Rejected alternatives:**

- Mapping NetworkPolicy drift to `START` was rejected because Pod replacement is
  unnecessary and more disruptive than the existing in-place boundary.
- Treating missing evidence as drift was rejected because current watch and
  failover reports intentionally omit authoritative comparison evidence.
- Clearing drift on command dispatch was rejected because only fresh
  authoritative observation proves convergence.

### runtime-260804/ADR-D6: Enforce one current Kubernetes Provider protocol

**Affected requirements:** `runtime-260804/REQ-2`, `REQ-5`

The Kubernetes Provider protocol advances from
`agent-runtime-provider-kubernetes-v1` to
`agent-runtime-provider-kubernetes-v2`, and its implementation version advances
with it. Runtime Control accepts only that exact protocol for Provider kind
`kubernetes` before connection registration or command authority is granted.
Docker retains its unchanged protocol because its observation contract does not
change in this snapshot.

The optional reconciliation message belongs only to the current v2 contract:
absence means a current watch, failover, or other report did not perform
authoritative comparison. It is not an old-Provider discriminator or compatibility
fallback.

Deployment drains old Control authority, applies the schema and current Control,
then starts the Kubernetes v2 Provider. A reconnecting v1 Provider is rejected.
Cross-version rollback and mixed-version serving are unsupported; recovery is
roll-forward to the coordinated current version.

**Rejected alternatives:**

- Declaring coordinated deployment without a server-side version gate was rejected
  because current registration validates only self-consistency between the
  registration and capability contract.
- Keeping protocol v1 was rejected because the cache-based Provider could register
  and regain command authority.
- Treating protobuf unknown-field decoding as compatibility was rejected because
  wire mechanics do not create a supported mixed-version product contract.

### runtime-260804/ADR-D7: Remove Provider-local command-history authority

**Affected requirements:** `runtime-260804/REQ-1`, `REQ-2`, `REQ-4`, `REQ-5`

The Kubernetes Provider removes `_CommandPolicyKey`, `_VerifiedCommandPolicy`,
`_verified_command_policies`, both `_fail_closed_without_command_policy`
implementations, cache invalidation branches, and tests that require a healthy Pod
to report `starting` after Provider restart.

`observe()` compares the actual NetworkPolicy with the expected policy and attaches
kind-scoped evidence while deriving lifecycle exclusively from the Pod. Watch and
failover reports derive lifecycle exclusively from backend resources and omit
reconciliation evidence. The Living Spec paragraph that makes command history a
watch-report trust authority is replaced by the new Provider/Control boundary.

### runtime-260804/ADR-D8: Reject unsupported reconciliation kinds

**Affected requirements:** `runtime-260804/REQ-3`, `REQ-4`, `REQ-5`

The Kubernetes Provider v2 reconciliation contract accepts exactly one kind:
`network_policy`. Runtime Control rejects the complete report before persistence
when evidence contains another kind. It does not ignore, preserve without action,
or partially consume an unsupported kind.

Adding another kind requires a new Requirements/ADR/Design snapshot and a
coordinated Provider protocol version change. An older Control version is never
expected to tolerate or silently discard a newer Provider's reconciliation
semantics.

**Rejected alternatives:**

- Ignoring unknown kinds was rejected because it creates old-Control/new-Provider
  semantic fallback.
- Persisting unknown kinds without action was rejected because durable state would
  contain evidence with no approved interpretation or recovery contract.

## Consequences

- Provider deployment no longer fabricates a Runtime lifecycle transition.
- NetworkPolicy drift remains fail-closed operationally because Control records it
  durably and dispatches in-place repair, but lifecycle observation stays truthful.
- A Provider reconnect requires a fresh explicit observation before old
  generation drift can be repaired.
- A new reconciliation kind requires a new coordinated protocol version and
  development snapshot.
- Obsolete Kubernetes Provider protocol versions cannot reconnect to current
  Runtime Control.
- The implementation requires a current-contract protobuf field, generated Python
  artifacts, an Alembic migration, repository and reconciler changes, Provider
  changes, and replacement tests and Living Specs.
