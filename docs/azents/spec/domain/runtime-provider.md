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
  - python/apps/azents/src/azents/services/runtime_provider_selection/**
  - python/apps/azents/src/azents/services/runtime_execution_policy/**
  - python/apps/azents/src/azents/repos/runtime_execution_policy/**
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
  - typescript/apps/azents-admin-web/src/features/runtime-execution/**
  - typescript/apps/azents-admin-web/src/trpc/routers/runtimeProvider.ts
  - typescript/apps/azents-admin-web/src/trpc/routers/runtimeExecution.ts
last_verified_at: 2026-07-27
spec_version: 12
---

# Runtime Provider

## Overview

A Runtime Provider is a durable operational resource identified by an opaque logical Provider ID and an internal resource ID. Providers may be registered by an Admin or by a trusted bootstrap declaration; both origins reconcile into the same Provider aggregate and management APIs. Provider controller connections do not create or discover Provider resources.

Provider authentication is a separate durable binding domain. A connection selects one explicit authentication method, verifies its evidence, resolves exactly one active binding, and derives the Provider identity from that binding. Registration payload fields are consistency checks only and cannot select a Provider or grant authority.

Providers are optional. A Provider must be enabled, active, connected, Workspace-eligible, and capable of satisfying the requested Runtime before a new logical Runtime can bind to it. Decommissioning, force-retired, disabled, disconnected, and contract-unaccepted Providers remain durable for Admin inventory but are not offered for new public discovery or selection.

## Policy and contract state

The aggregate stores lifecycle state, enablement, scope, Workspace availability mode, declared capabilities, the currently advertised contract revision, the accepted contract revision, active configuration revision, and an incrementing Admin policy version. The current pointer is Provider-reported state; the accepted pointer is Admin authority. Equality means the live advertisement is accepted, while inequality means the exact current advertisement requires review. Accepted contract revisions are immutable history. Never-accepted proposals are transient approval targets: a newer or restored Provider advertisement deletes every other unapproved row so only the current proposal remains actionable. Configuration revisions are immutable candidates that require Provider validation and explicit activation; active configuration is tied to the accepted contract and is never returned with secret plaintext.

After workload authentication and identity matching, Provider registration submits the complete
restricted capability contract. Runtime Control validates its implementation and protocol identity,
canonicalizes the payload, and creates or finds the Provider-local digest revision before accepting
the connection. A first or changed valid digest remains a candidate: the Provider may stay connected
for observation, but it is not provisioning-ready until a System Admin explicitly accepts that exact
revision. Admin routes expose contract history and expected-`admin_version` acceptance. Admin
Provider detail presents the current advertisement before immutable contract history and offers
acceptance only on that current candidate. List readiness is derived from the current and accepted
pointers; accepted history by itself never produces a review-ready state.
Only the Provider's current advertised contract may remain a candidate or be accepted. A newer
proposal deletes older never-accepted proposals, and an older revision cannot later replace the
current candidate. If the Provider advertises a digest that was accepted and later superseded,
that current drift creates a new candidate revision even though the same digest exists in accepted
history. Admin can therefore always review and restore the contract the connected Provider actually
advertises.

Admin routes expose inventory and mutable policy/availability operations under `/runtime-provider/v1/providers`. Public discovery exposes only safe option metadata under `/runtime-provider/v1/workspaces/{handle}/providers`; credentials, authentication evidence, encrypted secrets, audit state, and mutable Runtime bindings are excluded.

## Runtime binding

New logical Runtime creation uses one exact Provider candidate. Agent preference is evaluated before the Platform Runtime System Setting default, and no fallback occurs after an explicit candidate is ineligible. The resolver checks lifecycle, enablement, Platform scope, Workspace allow-list, connection readiness, accepted contract ownership/status, configuration validity, and requested capabilities.

The selected Provider resource ID, opaque logical ID, binding origin, contract/configuration revision identifiers, and policy digest are persisted on the logical Runtime. An immutable effective policy snapshot is attached before lifecycle dispatch. Later default, availability, contract, or configuration changes never move an existing logical Runtime.

A pre-contract Runtime with only its historical logical Provider ID is upgraded lazily at the same
selection boundary. The service resolves that exact logical ID, validates the accepted contract,
stores a `migration` resource binding, and attaches the initial immutable policy snapshot in one
transaction. This compatibility path preserves the logical Runtime, desired generation, and
Provider-owned workspace storage; it neither invokes reset nor selects a different Provider.

When no eligible Provider exists, Public Agent Runtime lifecycle endpoints return a stable `409` unavailable outcome instead of creating a partial Runtime or selecting a deployment/environment default.

## Runtime execution policy compatibility

Runtime execution policy is Provider-neutral typed product intent. Each Profile is a complete
authority ceiling; Workspace may only tighten every Profile it allows, and Agent may select an
allowed Profile and add only supported restrictive overrides. There is no separate installation-wide
execution-policy layer. `system-standard` is the reserved, editable baseline Profile. Ordinary Profiles are active or
retired and use expected-version mutation. Retiring an ordinary Profile preserves existing Agent
intent but makes affected selection unavailable until a valid Profile is chosen. Profile writes are
capability-gated, so unsupported authority cannot be introduced by profile creation or
replacement.

The reserved `system-standard` default permits unrestricted direct outbound
networking, represented by `network.egress=direct` with empty allow and deny destination sets.
This default applies to both the Runner and nested engine containers because the Kubernetes
NetworkPolicy selects the complete Runtime Pod. Image build, nested container execution, Compose,
and engine storage remain disabled until an Admin explicitly grants them through policy.

Raw Provider registration metadata is not product capability authority. The server-owned
management/status gate is authoritative: the resolver marks an unsatisfied Profile unavailable and
provisioning fails closed rather than dropping an unsupported module or selecting a weaker Runtime.
The immutable contract may include a typed `execution_policy` section declaring exact module
versions, privileged-engine implementation support, storage modes, network modes, and optional
resource maxima. Runtime resolution uses only the bound Provider's current accepted contract;
missing, candidate, rejected, malformed, or superseded declarations cannot grant authority. A new
target snapshot records and references that accepted contract revision even when the previous
snapshot used an older revision. A stale non-null Provider configuration remains unavailable until
it is validated against the newly accepted contract.

All execution-policy modules use version `1` until the contract is formally released. The current
resource shape replaces the earlier development shape in place; policy rows and snapshots are
migrated to v1, and Runtime Control contains no v2 parser or fallback. The immutable Provider
command envelope transports the effective policy as canonical JSON text, not protobuf `Struct`.
Snapshot persistence uses the same canonical JSON text and does not retain the removed JSONB field.

Agent intent is independent from a physical Runtime. Saving Agent Profile/override intent does not
advance Runtime desired generation. Explicit Apply attaches an immutable target snapshot and
generation. Profile or Workspace tightening automatically creates a narrower target without a
second Agent Apply, while authority expansion remains pending until explicit Apply; convergence
preserves Agent Workspace storage and does not invoke reset or terminal delete. Mode changes and their
dependent fields are projected atomically: Docker storage mode travels with Docker storage capacity,
and outbound network mode travels with its CIDR sets. Selective Kubernetes resource tightening also
normalizes CPU and memory requests so neither can exceed its resulting limit. Audit and public projections contain only bounded policy metadata, reason codes, source
layers, digests, and generations.

The installation management gate exposes image build, container run, Compose, `none` or
`ephemeral` Docker storage, and all three implemented network policies: system traffic only,
allowlisted IP CIDRs, and all IP addresses. These network policies are always advertised without a
deployment-owned capability filter. The Kubernetes Provider enforces the selected mode with a
generation-fenced NetworkPolicy that always permits required DNS and Runtime Control traffic,
adds only the selected allowlisted IPv4/IPv6 CIDRs in allowlist mode, or adds IPv4/IPv6 default
routes in all-address mode. Denied CIDRs are subtracted from otherwise allowed IP blocks. The Helm
deployment NetworkPolicy remains a separate hard cap: its denied CIDRs, explicit CIDR exceptions,
and selector/port egress rules are passed into the Provider and intersected with each generated
Runtime policy. Deployment-only selector/port exceptions are added only to all-address mode, never
to a Profile allowlist or system-only policy.

`container.resources/v1` separates optional Kubernetes CPU and memory requests from optional
limits. Ephemeral storage is one fixed allocation applied as the same request and limit. Optional
PID and container-count values bound nested Docker workloads when set; `null` means unlimited and
skips the corresponding aggregate Gateway check. Temporary Docker image/container data uses a
separate bounded engine-only `emptyDir`. Persistent workspace storage configures the Runtime
PVC request: expansion is applied in place, but a smaller configured value is retained until an
explicit operation deletes and recreates the PVC. Persistent Docker engine storage and
proxy-required egress remain unavailable because the Provider does not advertise them.
Admin/Public surfaces must not expose Provider credentials, socket paths, raw manifests, Kubernetes
resource names, or generic privileged controls.

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
