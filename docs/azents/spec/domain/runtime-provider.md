---
title: "Runtime Provider"
created: 2026-07-22
tags: [backend, frontend, admin, runtime, security, infra]
spec_type: domain
domain: runtime-provider
code_paths:
  - python/apps/azents/src/azents/rdb/models/runtime_provider.py
  - python/apps/azents/src/azents/rdb/models/runtime_provider_policy.py
  - python/apps/azents/src/azents/repos/runtime_provider/**
  - python/apps/azents/src/azents/repos/runtime_provider_policy/**
  - python/apps/azents/src/azents/services/runtime_provider_admin/**
  - python/apps/azents/src/azents/services/runtime_provider_public/**
  - python/apps/azents/src/azents/services/runtime_provider_selection/**
  - python/apps/azents/src/azents/api/admin/runtime_provider/**
  - python/apps/azents/src/azents/api/public/runtime_provider/**
  - python/apps/azents/src/azents/rdb/models/agent_runtime.py
  - python/apps/azents/src/azents/services/agent_runtime/**
  - infra/charts/azents/templates/runtime-provider-kubernetes/**
  - infra/charts/azents/values.yaml
  - infra/charts/azents/values.schema.json
  - typescript/apps/azents-admin-web/src/app/runtime-providers/**
  - typescript/apps/azents-admin-web/src/features/runtime-providers/**
  - typescript/apps/azents-admin-web/src/trpc/routers/runtimeProvider.ts
last_verified_at: 2026-07-22
spec_version: 1
---

# Runtime Provider

## Overview

A Runtime Provider is a durable operational resource identified by an opaque logical Provider ID and an
internal resource ID. Providers may be registered by an Admin or a trusted bootstrap declaration. Both
origins converge on the same aggregate and management APIs. Provider controller connections do not
create or discover Provider resources.

Providers are optional. A Provider must be enabled, active, connected, Workspace-eligible, and capable
of satisfying the requested Runtime before a new logical Runtime can bind to it. Decommissioning,
force-retired, disabled, disconnected, and contract-unaccepted Providers remain durable for Admin
inventory but are not offered for new public discovery or selection.

## Policy and contract state

The aggregate stores lifecycle state, enablement, scope, Workspace availability mode, declared
capabilities, accepted contract revision, active configuration revision, and an incrementing Admin
policy version. Contract revisions are immutable and move through candidate, accepted, rejected, and
superseded states. Configuration revisions are immutable candidates that require Provider validation
and explicit activation; active configuration is tied to the accepted contract and is never returned
with secret plaintext.

Admin routes expose inventory and mutable policy/availability operations under
`/runtime-provider/v1/providers`. Public discovery exposes only safe option metadata under
`/runtime-provider/v1/workspaces/{handle}/providers`; credentials, encrypted secrets, audit state,
and mutable Runtime bindings are excluded.

## Runtime binding

New logical Runtime creation uses one exact Provider candidate. Agent preference is evaluated before the
Platform Runtime System Setting default, and no fallback occurs after an explicit candidate is
ineligible. The resolver checks lifecycle, enablement, Platform scope, Workspace allow-list,
connection readiness, accepted contract ownership/status, configuration validity, and requested
capabilities.

The selected Provider resource ID, opaque logical ID, binding origin, contract/configuration revision
identifiers, and policy digest are persisted on the logical Runtime. An immutable effective policy
snapshot is attached before lifecycle dispatch. Later default, availability, contract, or configuration
changes never move an existing logical Runtime.

When no eligible Provider exists, Public Agent Runtime lifecycle endpoints return a stable `409`
unavailable outcome instead of creating a partial Runtime or selecting a deployment/environment default.

## Deployment boundary

The Kubernetes Provider remains disabled by default. When enabled, its Provider credential is read only
from an operator-managed Secret reference and is distinct from Runtime Control authentication. The Helm
bootstrap source renders an authoritative declaration file, including an explicit empty provider list
when the adapter is disabled. Admin Provider policy cannot mutate cluster RBAC, NetworkPolicy,
RuntimeClass, Secret contents, or other deployment-owned security controls.
