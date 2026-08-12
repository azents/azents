---
title: "Runtime Provider"
created: 2026-07-22
tags: [backend, frontend, admin, runtime, security, infra]
spec_type: domain
domain: runtime-provider
code_paths:
  - python/apps/azents/src/azents/rdb/models/runtime_provider.py
  - python/apps/azents/src/azents/rdb/models/runtime_provider_bootstrap.py
  - python/apps/azents/src/azents/rdb/models/runtime_provider_policy.py
  - python/apps/azents/src/azents/rdb/models/runtime_provider_binding.py
  - python/apps/azents/src/azents/rdb/models/runtime_provider_control.py
  - python/apps/azents/src/azents/repos/runtime_provider/**
  - python/apps/azents/src/azents/repos/runtime_provider_binding/**
  - python/apps/azents/src/azents/repos/runtime_provider_control/**
  - python/apps/azents/src/azents/repos/runtime_provider_policy/**
  - python/apps/azents/src/azents/services/runtime_provider_admin/**
  - python/apps/azents/src/azents/services/runtime_provider_binding_admin/**
  - python/apps/azents/src/azents/services/runtime_provider_bootstrap/**
  - python/apps/azents/src/azents/services/runtime_provider_control/**
  - python/apps/azents/src/azents/services/runtime_provider_contract/**
  - python/apps/azents/src/azents/services/runtime_provider_public/**
  - python/apps/azents/src/azents/core/runtime_profile.py
  - python/apps/azents/src/azents/rdb/models/runtime_profile.py
  - python/apps/azents/src/azents/repos/runtime_profile/**
  - python/apps/azents/src/azents/services/runtime_profile_admin/**
  - python/apps/azents/src/azents/services/runtime_profile_compatibility/**
  - python/apps/azents/src/azents/services/runtime_profile_reconciliation/**
  - python/apps/azents/src/azents/services/runtime_profile_resolution/**
  - python/apps/azents/src/azents/services/runtime_profile_workspace/**
  - python/apps/azents/src/azents/services/runtime_recreation/**
  - python/apps/azents/src/azents/api/admin/runtime_provider/**
  - python/apps/azents/src/azents/api/admin/runtime_provider_enrollment/**
  - python/apps/azents/src/azents/api/public/runtime_provider/**
  - python/apps/azents/src/azents/api/public/runtime_profile/**
  - python/apps/azents/src/azents/api/public/agent_runtime/**
  - python/apps/azents/src/azents/rdb/models/agent_runtime.py
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents-runtime-provider-kubernetes/**
  - python/apps/azents-runtime-provider-docker/**
  - python/libs/azents-runtime-control/src/azents_runtime_control/**
  - proto/azents/runtime_control/v1/runtime_provider_control.proto
  - infra/charts/azents/templates/runtime-provider-kubernetes/**
  - infra/charts/azents/templates/server/rbac.yaml.tpl
  - infra/charts/azents/templates/server/runtime-control-deployment.yaml.tpl
  - infra/charts/azents/templates/server/runtime-provider-bootstrap-configmap.yaml.tpl
  - infra/charts/azents/values.yaml
  - infra/charts/azents/values.schema.json
  - typescript/apps/azents-admin-web/src/app/runtime-providers/**
  - typescript/apps/azents-admin-web/src/features/runtime-providers/**
  - typescript/apps/azents-admin-web/src/trpc/routers/runtimeProvider.ts
  - typescript/apps/azents-web/src/features/runtime-profiles/**
  - typescript/apps/azents-web/src/features/chat/workspace/components/RuntimeConfigurationStatus.tsx
last_verified_at: 2026-08-12
spec_version: 25
---

# Runtime Provider

## Overview

A Runtime Provider is a durable operational resource identified by an opaque logical Provider ID
and an internal resource ID. Providers may be registered by an Admin or by a trusted bootstrap
declaration; both origins reconcile into the same Provider aggregate and management APIs. Provider
controller connections do not create or discover Provider resources.

Provider authentication is a separate durable binding domain. A connection selects one explicit authentication method, verifies its evidence, resolves exactly one active binding, and derives the Provider identity from that binding. Registration payload fields are consistency checks only and cannot select a Provider or grant authority.

Providers are optional. A Provider must be enabled, active, Workspace-eligible, and currently
advertise a valid capability contract that satisfies the exact selected infrastructure Profile
before the Runtime configuration can become ready. A live connection is separate operational
readiness required before lifecycle dispatch or operation qualification. Decommissioning,
force-retired, disabled, invalid-capability, and incompatible Providers remain durable for Admin
inventory but cannot satisfy new Runtime creation or recreation; disconnected Providers retain
their valid configuration identity while physical work waits for reconnect.

## Policy and capability state

The aggregate stores lifecycle state, enablement, scope, Workspace availability mode, declared
capabilities, the currently advertised capability revision, active Provider-global operational
configuration revision, and an incrementing Admin policy version. The exact current valid
advertisement is immediately authoritative for compatibility and command readiness. Capability
history is immutable audit evidence; there is no Admin acceptance pointer, acceptance route, or
historical revision pinning authority.

After workload authentication and identity matching, Provider registration submits the complete
capability contract. Runtime Control validates implementation/protocol identity and the complete
typed contract, canonicalizes it, and creates or reuses the Provider-local digest revision before
registering the connection. A changed valid advertisement immediately changes current compatibility.
An invalid advertisement is rejected and cannot retain command authority through older history.

Both Providers advertise Profile schema versions 1 and 2. Schema v2 no longer carries an
Azents-owned process-containment module and does not require a containment capability. Historical
stored schema-v2 documents with `process_containment: null` are normalized to the current direct
contract; a non-null value is invalid and cannot silently execute through the direct path.
Admin Profile write ingress rejects unknown removed fields instead of stripping them. Runner
startup rejects `AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG`, and bundled Provider startup rejects every
`AZ_RUNTIME_PROVIDER_PROCESS_CONTAINMENT_*` variable, including empty values, so version-skewed
deployment configuration cannot silently select direct execution.
Infrastructure-level process isolation remains an operator-owned deployment boundary rather than a
Provider capability or Profile option.

Provider-global operational configuration revisions remain a separate Provider-owned mechanism.
They may configure the Provider process but cannot contain Workspace or Agent Runtime Profile
authority. Configuration candidates require Provider validation and explicit Admin activation, and
secret plaintext is never returned.

Admin routes expose inventory and mutable policy/availability operations under `/runtime-provider/v1/providers`. Public discovery exposes only safe option metadata under `/runtime-provider/v1/workspaces/{handle}/providers`; credentials, authentication evidence, encrypted secrets, audit state, and mutable Runtime bindings are excluded.

## Runtime binding

An Agent may be Runtime-free and have no logical Runtime row or Provider binding. Explicit Runtime
addition selects one available Workspace Runtime Profile, creates or rearms the one logical Runtime
in stopped desired state, and does not allocate compute. A retained terminally deleted logical
Runtime may be rearmed only after exact deletion acknowledgement; rearm advances desired generation,
clears incarnation-scoped Provider/Runner observation and Workspace evidence, and preserves no old
physical resource authority.

A managed Agent selection points to one Workspace Runtime Profile. That Profile names one exact Provider
resource and one infrastructure Profile owned by that Provider. The resolver does not evaluate an
Agent Provider preference, Platform default, environment default, or fallback Provider. It checks
the exact Profile ownership, lifecycle, Provider lifecycle/enablement/scope/Workspace eligibility,
current capability, infrastructure compatibility, and Workspace policy. Live connection state does
not participate in desired configuration status, sequence, or digest.

The logical Runtime stores durable Provider routing identity and a monotonic
`configuration_sequence` high-water mark. One bounded `runtime_configuration_states` row stores at
most one desired slot and one applied slot. A ready or blocked desired document snapshots the exact
Provider capability, infrastructure Profile, Workspace Runtime Profile, Agent selection, source
versions, and resolved configuration required by the current target; those identifiers are scalar
evidence rather than foreign keys to mutable Profile resources.

Every materially new desired target, including a source-authority change, lifecycle generation
advance, blocked result, or transition to unconfigured state, receives the next positive
configuration sequence. Repeating an identical current target does not allocate another sequence.
Provider/Profile changes overwrite the desired slot; they do not silently move the Agent to another
Profile or Provider. Provider and Runner evidence is accepted only for the exact Runtime, desired
generation, positive configuration sequence, digest, and current connection generation. Returning
to an earlier document therefore cannot reuse evidence from its earlier application.

Provider infrastructure chooses and mounts durable storage for Runner workloads. Bundled Providers
set Runner `HOME` and working directory to the configured mount path, but Provider registration and
lifecycle reports do not advertise an Agent Workspace path. The Runner's current-generation report
is the metadata authority for the effective absolute path.

When the exact selection is missing or unavailable, Public Runtime creation/start/restart/reset/
recreate returns a bounded `409` conflict instead of persisting a substitute target. Stop and
terminal delete remain available where required to reduce authority or finalize decommissioning.

A Workspace Owner may permanently delete a Workspace Runtime Profile with optimistic version
fencing. The PostgreSQL transaction physically deletes the Profile, clears a matching Workspace
default and every matching Agent selection while advancing their versions, and chooses no fallback.
Each affected managed Runtime advances its configuration sequence and overwrites desired state as
`unconfigured` with reason `runtime_profile_required`. Its Provider binding, applied slot, running
workload, Runner-reported Workspace path, and Agent Workspace storage remain until an explicit
replacement or terminal Runtime removal. Active recreation work targeting the deleted Profile is
completed with affected pending or running items skipped as `target_deleted`.

While desired state is unconfigured, create/start/restart/reset/recreate and Runner-dependent work
that requires a current Profile are unavailable. Stop, read-only observation where applicable, and
terminal removal remain available. Selecting a replacement Profile writes a higher-sequence ready
desired slot; exact Provider and Runner acknowledgement promotes it and overwrites the prior applied
slot. Exact terminal-removal finalization deletes the remaining configuration-state row while the
Runtime-owned sequence high-water remains for later rearm fencing.

Permanent Runtime removal may request terminal delete while the Provider is disconnected. The
operation remains pending until a current authoritative Provider report acknowledges the exact
requested desired generation; an already-absent backend resource may acknowledge success.
Disconnection, an ambiguous outcome, or a stale Provider generation never proves deletion.

## Infrastructure Profile compatibility and customer authority

Each Provider owns typed infrastructure Profiles for its native substrate:

- Kubernetes Providers own Pod Profile schema v1 or v2 containing typed Runner resources,
  scheduling, Workspace PVC, network preset, and optional DinD modules.
- Docker Providers own Container Profile schema v1 or v2 containing typed resources and
  Docker-network placement.

Profile v1 and Profile v2 both describe direct Runner execution. Profile v2 retains its versioned
contract shape for stored compatibility but has no process-containment field. Workspace, Agent,
Session, and user surfaces select the complete infrastructure Profile without exposing an
Azents-owned process-isolation toggle.

Infrastructure Profile writes are Provider-kind-specific, expected-version-fenced, and validated
against the Provider's current capability contract. Missing or removed capability makes dependent
Profiles unavailable; the server never drops an unsupported field or lowers to a weaker Profile.

A System Administrator may permanently delete one Provider-owned infrastructure Profile through
the matching Pod- or Container-Profile Admin route. Opening the deletion review reads a fresh,
bounded PostgreSQL projection of every current Workspace Runtime Profile reference plus the count
of currently running Runtimes that retain the target only in applied configuration. Current
Workspace Runtime Profile references, including disabled Profiles, block deletion. Applied-only
Runtime evidence is informational and never creates a reference or lifecycle authority.

Deletion submits the exact reviewed Profile version. In one PostgreSQL transaction the repository
locks the exact Provider/Profile row, rechecks current Workspace Runtime Profile references,
terminalizes active target-scoped recreation operations with non-terminal items skipped as
`target_deleted`, and physically removes only the infrastructure Profile. The restrictive
Workspace-Profile foreign key remains the final concurrency backstop. Stale version, new reference,
already-absent target, kind mismatch, and unexpected integrity conflict are distinct bounded
outcomes, and every failure rolls back without partial mutation.

Infrastructure Profile deletion does not rewrite Workspace Runtime Profiles, defaults, Agent
selections, desired or applied Runtime configuration, Provider bindings, running workloads,
Runner-reported Agent Workspace paths, or Agent Workspace storage. A deletion can therefore succeed
while a running Runtime retains the deleted Profile ID as applied historical evidence. Future
create, start, restart, reset, or recreation still requires current Profile authority and cannot
restore or substitute the deleted resource. The deleted Provider-scoped display name becomes
available for a new Profile.

A separate System-Admin-only read route exposes one exact Workspace Runtime Profile with Workspace,
Provider, infrastructure Profile, lifecycle, policy, version, selected-Agent count, and running
Runtime count. It is read-only, does not require Workspace membership, and grants no customer
Workspace mutation authority. The Admin deletion review links blocking references to this detail
surface while retaining the Provider-page deletion context.

A Workspace Runtime Profile is the complete customer choice. It selects one infrastructure Profile
and may add only the Workspace policy supported by that contract. Kubernetes network policy is
restrictive-only and composes with Provider and infrastructure hard boundaries. Required DNS and
Runtime Control communication remains Platform protected. Docker rejects Workspace network policy.

The complete resolved configuration travels through the canonical Runtime configuration envelope.
The Provider reports exact configuration evidence for the current desired generation. Applied state
is promoted only after the Provider acknowledgement and a matching ordinary Runner state report.
There is no policy snapshot, separate Apply action, dedicated Runner configuration-update
operation, or legacy parser fallback.

NetworkPolicy-only Kubernetes changes may be adopted in place. PodSpec, PVC, and Docker changes
require explicit durable recreation. Provider-, infrastructure-Profile-, and Workspace-Profile-
scoped recreation operations snapshot exact target IDs and versions, use bounded concurrency and
retries, skip stale or superseded targets, and preserve Workspace storage. PVC expansion may apply
to the current claim; shrink waits for an explicit destructive reset or terminal delete.

Kubernetes Provider v2 reports Pod lifecycle directly and does not use process-local command or
NetworkPolicy verification history as lifecycle authority. A current `OBSERVE` completion may include
one structured `network_policy` observation; watch, failover, lifecycle-only, and non-`OBSERVE`
completion reports may omit it. The Provider owns only factual backend observation and the
non-destructive configuration application. Runtime Control's report sink validates identity,
generation, lifecycle, and configuration evidence and persists only those ordinary facts; it never
persists drift, a repair claim, or retry state. The gRPC bridge retains command-type correlation only
for the live stream. A valid current `OBSERVE` completion with `network_policy:drifted` is handed
once to the Lifecycle Reconciler, which re-fences the Runtime, Provider generation, and
equal desired/applied configuration sequence while holding that Runtime row through exact
configuration lookup and `UPDATE_CONFIGURATION` append, never `START`. Pending lifecycle dispatch
and terminal deletion block the handoff. Control logs the transient handoff and successful dispatch
with Runtime/Provider identity, Provider and desired generations, configuration sequence,
NetworkPolicy kind, and reason, but does not persist those fields as repair state. Lost completion,
stream/control restart, and dispatch failure discard the handoff; a later periodic `OBSERVE` is the
only retry mechanism. Policy comparison excludes the historical Provider-generation transport
label but keeps desired-generation, configuration identity, selectors, and rules exact.

The current Kubernetes protocol accepts only `network_policy` reconciliation evidence. A report
containing any other kind is rejected as a whole, and adding a kind requires a coordinated new
Provider protocol and development snapshot. Kubernetes v1 cannot register with current Runtime
Control; only `agent-runtime-provider-kubernetes-v2` obtains connection and command authority.
Docker Provider protocol behavior is unchanged.

Admin/Public surfaces expose typed schema versions and values, current compatibility, impact,
desired/applied status, and bounded recreation progress. These surfaces do not expose Provider
credentials, socket paths, raw manifests, Kubernetes resource names, or generic privileged
controls.

## Authentication bindings

A Provider authentication binding is a durable, method-neutral resource that records a stable binding ID, Provider ID, authentication method, normalized subject, lifecycle state, ownership source and reference, non-secret method configuration, optimistic mutation version, authentication and connection-health timestamps, revocation metadata, and creation/update timestamps. Active subject uniqueness is scoped by method. A Provider can own multiple bindings for credential rotation, but every connection authenticates through one binding.

The supported methods are:

- `azents_issued_token`: a verifier-backed Provider credential belongs to the binding. It remains the method for Workspace Providers and manually enrolled Providers. Credential state and expiration must remain active for the binding to establish or retain command authority.
- `kubernetes_service_account`: a Kubernetes ServiceAccount subject and required audience identify a bootstrap-owned binding. It has no Provider credential, enrollment grant, synthetic credential row, or Secret representation.

Authentication has no method fallback. A missing, unknown, invalid, expired, revoked, inactive, mismatched, or ambiguously resolved method/binding is rejected before a connection is registered. The resolved binding, Provider, normalized subject, and evidence expiry are retained as connection authority. For issued tokens, that authority additionally requires the active credential; for Kubernetes workload identity, it requires the same active binding and unexpired verified workload evidence. Revocation removes credential and retained connection authority without changing the opaque Provider identity.

Binding audit records creation, update, rotation, authentication, revocation, conflict, and connection lifecycle using metadata only. Bearer tokens, verifiers, projected token content, encrypted secret plaintext, and Runner evidence are never included in binding inventory, detail, audit, logs, or public discovery.

## Admin authentication management

System Admins can list Provider-scoped authentication bindings, inspect a binding, and view metadata-only audit history. Safe projections include method, normalized subject, ownership, lifecycle, health, timestamps, active connection state, revocation state, and non-secret method configuration.

Admin creation produces an active Admin-owned `azents_issued_token` binding for a non-terminal Provider. Rotation and revocation accept only an existing active Admin-owned `azents_issued_token` binding. Mutations require the current optimistic `admin_version`; stale versions return a bounded conflict with the current safe projection. Rotation returns an enrollment grant secret exactly once and does not persist it in UI query caches, browser storage, audit rows, or logs. The existing public grant exchange remains one-time and resolves authority from the durable binding ID.

Bootstrap-owned bindings and `kubernetes_service_account` bindings are read-only to Admin mutation. Binding-scoped revocation records actor and reason metadata, removes active credential and retained connection authority, and preserves Provider identity and audit history. Existing-binding mutation is binding-authoritative: a Provider ID scopes inventory and creation but cannot select another binding for rotate or revoke.

The Admin Runtime Provider detail UI preserves its existing master-detail and responsive Drawer layout while adding an Authentication section for binding inventory, safe detail, audit, create/rotate/revoke actions where authorized, ownership state, and bounded failure messages.

## Deployment boundary

The Kubernetes Provider remains disabled by default. When enabled, Helm renders an authoritative typed bootstrap declaration for the opaque `system-kubernetes` Provider and its `kubernetes_service_account` binding. The declaration contains the normalized ServiceAccount subject, namespace, ServiceAccount name, required audience, and bootstrap ownership identity; bootstrap reconciliation creates or reconciles that durable binding without issuing or persisting a Provider credential.

The long-running Provider receives a dedicated read-only projected ServiceAccount token at `AZ_RUNTIME_PROVIDER_SERVICE_ACCOUNT_TOKEN_FILE`. Its audience is exactly `azents-runtime-control`; the Provider selects `kubernetes_service_account` explicitly, reads the current token immediately before connecting, and reconnects after projected-token rotation without logging token content. The default auto-mounted Kubernetes API token is not the authentication contract.

Runtime Control uses its server ServiceAccount to create Kubernetes TokenReview requests. It accepts workload identity only when TokenReview reports an authenticated result with the exact required audience and `system:serviceaccount:<namespace>:<name>` subject, and that subject resolves to exactly one active bootstrap-owned binding. The Provider ServiceAccount may manage its Runtime Pods/PVCs and leader Lease but cannot create TokenReviews or write Secrets.

The active chart has no Provider credential or shared Runtime Control authentication values, credential bootstrap Job, staging/final Provider credential Secret, credential volume, or bootstrap Secret RBAC. Runtime Control TLS remains mandatory and separate from Provider authentication. Admin Provider policy cannot mutate cluster RBAC, NetworkPolicy, RuntimeClass, Secret contents, or other deployment-owned security controls.

Authentication rollout does not render, own, select, delete, rename, or recreate Runtime PersistentVolumeClaims or PersistentVolumes. Credential-driven Runtime Pod replacement reuses the existing PVC; only the established explicit Runtime reset or terminal-delete operations may invoke PVC deletion.

Runtime workload security is deployment-owned. Providers retain ordinary non-root workload
hardening and substrate controls, while node security, RuntimeClass selection, AppArmor, gVisor,
network controls, and infrastructure access are operator responsibilities outside Profile input.
Admin Profile editing cannot mutate those deployment boundaries.

## Version history

- **25 (2026-08-12):** Added System-Admin exact-version infrastructure Profile hard deletion,
  fresh blocking-reference and applied-only impact projection, target-scoped recreation
  terminalization, Runtime/Workspace preservation, and membership-independent Admin Workspace
  Runtime Profile detail.
- **24 (2026-08-11):** Replaced Agent Runtime configuration-history references with bounded
  desired/applied state slots, positive sequence/digest/generation fencing, exact promotion and
  cleanup, and Owner hard-delete behavior without fallback or running-Workspace disruption.
- **23 (2026-08-11):** Removed the Azents-owned process-containment capability, Profile module,
  derived status projections, and Provider deployment preparation while retaining schema-v2
  compatibility for historical null fields and rejecting active containment requests.
- **22 (2026-08-11):** Made Kubernetes process containment a permanent Provider capability and
  removed the deployment feature flag that conditionally advertised Profile schema v2.
- **21 (2026-08-10):** Added optional logical Runtime binding, explicit stopped add and
  higher-generation rearm, and reconnect-safe exact-generation terminal deletion for permanent
  Agent Runtime removal.

- **20 (2026-08-09):** Separated durable Runtime configuration identity from live Provider
  connectivity so transient rollout reconnect gaps retain ready desired state while dispatch and
  operation qualification still require current connection authority.
- **19 (2026-08-09):** Added Profile v2 portable process containment, deployment-owned capability
  advertisement plus per-Runtime qualification, explicit recreation, safe derived product
  projections, and fail-closed Docker/Kubernetes preparation.
- **18 (2026-08-05):** Serialized bounded repair configuration lookup and append with the current
  Runtime row, added lifecycle/terminal fences, and recorded transient structured correlation logs.
- **17 (2026-08-05):** Removed durable Runtime drift/repair projection. A live-stream-correlated
  `OBSERVE` completion may make one fenced `UPDATE_CONFIGURATION` handoff; periodic observation is
  the sole retry path.
- **16 (2026-08-04):** Removed Kubernetes Provider-local NetworkPolicy lifecycle authority, added
  strict v2 structured drift evidence, and made Runtime Control the durable fenced repair owner.
- **15 (2026-08-03):** Removed Agent Workspace metadata from Provider capability and lifecycle reports; bundled Providers now configure Runner `HOME` and working directory while Runner reports the effective path.
- **14 (2026-07-31):** Replaced accepted-contract and hierarchical execution-policy authority with
  the authenticated current valid capability, Provider-owned typed infrastructure Profiles,
  Workspace-owned exact Runtime Profiles, desired/applied configuration evidence, and scoped
  recreation.
- **13 (2026-07-28):** Removed the Container Policy Gateway and unenforceable granular Docker, network, PID, and nested-container controls; Docker is one complete direct-DIND capability bounded by Kubernetes resources, storage, and the deployment NetworkPolicy hard cap.
- **12 (2026-07-27):** Persisted the exact current Provider advertisement separately from accepted history, made Admin readiness and acceptance follow that pointer, and made dependent storage/network policy projection atomic.
- **11 (2026-07-27):** Made the currently advertised Provider contract the sole approval target, deleted stale never-accepted proposals, and allowed a previously accepted digest to be proposed again after drift.
- **10 (2026-07-27):** Unified every unreleased execution-policy module on v1, migrated stored policies without a v2 compatibility path, replaced protobuf Struct and snapshot JSONB with canonical JSON text, and prevented stale contract acceptance.
- **9 (2026-07-27):** Advertised all implemented network modes, defined resource module v1 request/limit semantics, and added Profile-controlled persistent workspace capacity with deferred shrink.
- **8 (2026-07-27):** Removed the installation-wide execution-policy ceiling and made each editable Profile the complete authority ceiling.
- **7 (2026-07-27):** Made unrestricted direct outbound networking the installation and reserved Standard default while leaving nested container authority disabled.
- **6 (2026-07-27):** Added accepted typed execution-policy capabilities as the authority source for Kubernetes engine features.
- **5 (2026-07-27):** Connected authenticated Provider contract proposal, immutable candidate persistence, explicit Admin acceptance, and storage-preserving legacy Runtime policy binding.
- **4 (2026-07-26):** Added restrictive Runtime Execution Profile compatibility, explicit Apply versus automatic tightening convergence, safe policy projections, and the current fail-closed privileged-engine boundary.
- **3 (2026-07-23):** Promoted durable authentication bindings, explicit issued-token and Kubernetes ServiceAccount methods, Admin binding lifecycle, TokenReview workload identity, secret-free Helm deployment, and Runtime storage preservation behavior.
- **2 (2026-07-23):** Added Provider policy, selection, and credential-bootstrap deployment behavior.
