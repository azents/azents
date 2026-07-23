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
  - python/apps/azents/src/azents/services/runtime_provider_public/**
  - python/apps/azents/src/azents/services/runtime_provider_selection/**
  - python/apps/azents/src/azents/api/admin/runtime_provider/**
  - python/apps/azents/src/azents/api/admin/runtime_provider_enrollment/**
  - python/apps/azents/src/azents/api/public/runtime_provider/**
  - python/apps/azents/src/azents/rdb/models/agent_runtime.py
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/main.py
  - infra/charts/azents/templates/runtime-provider-kubernetes/**
  - infra/charts/azents/templates/server/rbac.yaml.tpl
  - infra/charts/azents/templates/server/runtime-control-deployment.yaml.tpl
  - infra/charts/azents/templates/server/runtime-provider-bootstrap-configmap.yaml.tpl
  - infra/charts/azents/values.yaml
  - infra/charts/azents/values.schema.json
  - typescript/apps/azents-admin-web/src/app/runtime-providers/**
  - typescript/apps/azents-admin-web/src/features/runtime-providers/**
  - typescript/apps/azents-admin-web/src/trpc/routers/runtimeProvider.ts
last_verified_at: 2026-07-23
spec_version: 3
---

# Runtime Provider

## Overview

A Runtime Provider is a durable operational resource identified by an opaque logical Provider ID and an internal resource ID. Providers may be registered by an Admin or by a trusted bootstrap declaration; both origins reconcile into the same Provider aggregate and management APIs. Provider controller connections do not create or discover Provider resources.

Provider authentication is a separate durable binding domain. A connection selects one explicit authentication method, verifies its evidence, resolves exactly one active binding, and derives the Provider identity from that binding. Registration payload fields are consistency checks only and cannot select a Provider or grant authority.

Providers are optional. A Provider must be enabled, active, connected, Workspace-eligible, and capable of satisfying the requested Runtime before a new logical Runtime can bind to it. Decommissioning, force-retired, disabled, disconnected, and contract-unaccepted Providers remain durable for Admin inventory but are not offered for new public discovery or selection.

## Policy and contract state

The aggregate stores lifecycle state, enablement, scope, Workspace availability mode, declared capabilities, accepted contract revision, active configuration revision, and an incrementing Admin policy version. Contract revisions are immutable and move through candidate, accepted, rejected, and superseded states. Configuration revisions are immutable candidates that require Provider validation and explicit activation; active configuration is tied to the accepted contract and is never returned with secret plaintext.

Admin routes expose inventory and mutable policy/availability operations under `/runtime-provider/v1/providers`. Public discovery exposes only safe option metadata under `/runtime-provider/v1/workspaces/{handle}/providers`; credentials, authentication evidence, encrypted secrets, audit state, and mutable Runtime bindings are excluded.

## Runtime binding

New logical Runtime creation uses one exact Provider candidate. Agent preference is evaluated before the Platform Runtime System Setting default, and no fallback occurs after an explicit candidate is ineligible. The resolver checks lifecycle, enablement, Platform scope, Workspace allow-list, connection readiness, accepted contract ownership/status, configuration validity, and requested capabilities.

The selected Provider resource ID, opaque logical ID, binding origin, contract/configuration revision identifiers, and policy digest are persisted on the logical Runtime. An immutable effective policy snapshot is attached before lifecycle dispatch. Later default, availability, contract, or configuration changes never move an existing logical Runtime.

When no eligible Provider exists, Public Agent Runtime lifecycle endpoints return a stable `409` unavailable outcome instead of creating a partial Runtime or selecting a deployment/environment default.

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

- **3 (2026-07-23):** Promoted durable authentication bindings, explicit issued-token and Kubernetes ServiceAccount methods, Admin binding lifecycle, TokenReview workload identity, secret-free Helm deployment, and Runtime storage preservation behavior.
- **2 (2026-07-23):** Added Provider policy, selection, and credential-bootstrap deployment behavior.
