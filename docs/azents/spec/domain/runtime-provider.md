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
  - python/apps/azents/src/azents/rdb/models/agent_runtime.py
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/main.py
  - python/apps/azents-runtime-provider-docker/src/azents_runtime_provider_docker/main.py
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
last_verified_at: 2026-08-03
spec_version: 15
---

# Runtime Provider

## Overview

A Runtime Provider is a durable operational resource identified by an opaque logical Provider ID
and an internal resource ID. Providers may be registered by an Admin or by a trusted bootstrap
declaration; both origins reconcile into the same Provider aggregate and management APIs. Provider
controller connections do not create or discover Provider resources.

Provider authentication is a separate durable binding domain. A connection selects one explicit authentication method, verifies its evidence, resolves exactly one active binding, and derives the Provider identity from that binding. Registration payload fields are consistency checks only and cannot select a Provider or grant authority.

Providers are optional. A Provider must be enabled, active, connected, Workspace-eligible, and
currently advertise a valid capability contract that satisfies the exact selected infrastructure
Profile before a new Runtime incarnation can be created. Decommissioning, force-retired, disabled,
disconnected, invalid-capability, and incompatible Providers remain durable for Admin inventory but
cannot satisfy new Runtime creation or recreation.

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

Provider-global operational configuration revisions remain a separate Provider-owned mechanism.
They may configure the Provider process but cannot contain Workspace or Agent Runtime Profile
authority. Configuration candidates require Provider validation and explicit Admin activation, and
secret plaintext is never returned.

Admin routes expose inventory and mutable policy/availability operations under `/runtime-provider/v1/providers`. Public discovery exposes only safe option metadata under `/runtime-provider/v1/workspaces/{handle}/providers`; credentials, authentication evidence, encrypted secrets, audit state, and mutable Runtime bindings are excluded.

## Runtime binding

An Agent selection points to one Workspace Runtime Profile. That Profile names one exact Provider
resource and one infrastructure Profile owned by that Provider. The resolver does not evaluate an
Agent Provider preference, Platform default, environment default, or fallback Provider. It checks
the exact Profile ownership, lifecycle, Provider lifecycle/enablement/scope/Workspace eligibility,
live connection, current capability, infrastructure compatibility, and Workspace policy.

The logical Runtime stores routing identity plus the exact infrastructure Profile, Workspace
Runtime Profile, desired configuration revision, and applied configuration revision. The immutable
configuration revision stores the Provider capability revision and complete source identity.
Provider/Profile changes create a new authoritative desired revision; they do not silently move the
Agent to another Profile or Provider.

Provider infrastructure chooses and mounts durable storage for Runner workloads. Bundled Providers
set Runner `HOME` and working directory to the configured mount path, but Provider registration and
lifecycle reports do not advertise an Agent Workspace path. The Runner's current-generation report
is the metadata authority for the effective absolute path.

When the exact selection is missing or unavailable, Public Runtime creation/start/restart/reset/
recreate returns a bounded `409` conflict instead of persisting a substitute target. Stop and
terminal delete remain available where required to reduce authority or finalize decommissioning.

## Infrastructure Profile compatibility and customer authority

Each Provider owns typed infrastructure Profiles for its native substrate:

- Kubernetes Providers own Pod Profiles containing typed Runner resources, scheduling, Workspace
  PVC, network preset, and optional DinD modules.
- Docker Providers own Container Profiles containing typed resources and Docker-network placement.

Infrastructure Profile writes are Provider-kind-specific, expected-version-fenced, and validated
against the Provider's current capability contract. Missing or removed capability makes dependent
Profiles unavailable; the server never drops an unsupported field or lowers to a weaker Profile.

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

Admin/Public surfaces expose typed values, current compatibility, impact, desired/applied status,
and bounded recreation progress. They do not expose Provider credentials, socket paths, raw
manifests, Kubernetes resource names, or generic privileged controls.

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

## Version history

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
