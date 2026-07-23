---
title: "Bound Runtime Control Connections Requirements"
created: 2026-07-23
updated: 2026-07-23
tags: [runtime, provider, security, infra]
document_role: primary
document_type: requirements
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Requirements

- Snapshot: `runtimeauth-260723`
- Document reference: `runtimeauth-260723/REQ`

## Problem

The deployed Runtime Provider path requires operator-managed credentials that cannot exist until Azents and its database are already available. This contradicts trusted deployment bootstrap, causes an unbounded external-secret lifecycle as Providers are added, and currently blocks deployment recovery.

Runtime Control also admits Runtime Runners through one deployment-wide shared secret rather than a credential bound to one logical Runtime incarnation. Provider and Runner identity must be established from authenticated bindings without trusting a client-supplied identity.

Azents does not currently provide one durable authentication-binding model that can represent different Provider trust boundaries, expose binding lifecycle and health to Platform Admins, and allow additional authentication methods without redefining Provider identity or connection handling.

## Primary Actor

Deployment Operator

## Primary Scenario

1. A Deployment Operator prepares the complete trusted Platform Kubernetes Provider deployment before Azents or its database is available.
2. Azents starts and reconciles the known opaque `system-kubernetes` Provider registration from the trusted bootstrap declaration.
3. The Kubernetes Provider connects without an operator-created Provider secret, and Runtime Control authenticates it as the Provider bound to its trusted Kubernetes workload identity.
4. A Platform Admin can inspect the Provider's authentication method, bound subject, lifecycle, and connection health without viewing credential plaintext.
5. The Provider creates a Runtime Runner, which connects without a deployment-wide operator-created Runner secret and is authenticated as one current logical Runtime incarnation.
6. The Platform Provider and Runtime Runner become available, allowing the blocked deployment to recover.

## Supporting Scenarios

- A Workspace Provider outside the trusted Platform bootstrap boundary authenticates with a token issued by Azents through the existing enrollment lifecycle.
- A Platform Admin creates, observes, rotates, and revokes Provider authentication bindings through the Admin product surface while Provider identity remains unchanged.
- A trusted Platform Kubernetes Provider reconnects after Pod replacement and retains the same Provider identity through its workload identity binding.
- A stale or replayed Runtime Runner credential cannot claim a different Runtime or a newer Runtime incarnation.

## Goals

- Allow trusted Platform Kubernetes Provider deployment to be fully prepared before Azents or its database is available.
- Select Provider authentication according to the Provider trust boundary rather than its implementation kind alone.
- Bind authenticated Provider and Runner connections to durable server-known identities.
- Make Provider authentication methods and bindings first-class durable resources with lifecycle, audit, health, and Admin management.
- Allow new Provider authentication methods to integrate through one normalized authentication contract without method fallback.
- Remove operator-managed Provider and shared Runner credentials from the deployment path.
- Restore deployment availability with the complete target authentication model rather than an interim compatibility path.

## Ideal Goal

The completed authentication model treats authentication methods and authenticated identity bindings as first-class, extensible concepts. A Provider or Runner connection selects one declared method, succeeds only when that method resolves exactly one server-known identity binding, and never derives authority from registration payload claims. Platform workload identity, Azents-issued credentials, and future methods share this contract without sharing credentials or introducing operator-managed per-resource secrets.

The model provides lifecycle, audit, revocation, health, and Admin management for durable authentication bindings and supports additional workload identity environments without redefining Provider or Runtime identity.

## Delivery Scope

This delivery implements the complete ideal authentication model for the two currently required Provider methods: Kubernetes ServiceAccount workload identity and Azents-issued tokens. It includes durable binding persistence, lifecycle and audit, normalized verifier composition, Admin API/UI management, Runtime-bound Runner authentication, and deployment integration.

Additional workload identity implementations and cross-cluster trust policies remain future extensions of the completed model. They must not require another Provider identity or connection-domain redesign.

## Non-Goals

- Implement additional workload identity systems beyond Kubernetes in this recovery change.
- Replace the existing Workspace Provider enrollment and Azents-issued token lifecycle.
- Preserve the credential-bootstrap, external Provider Secret, or shared Runner token paths as compatibility fallbacks.
- Change Provider selection, Runtime lifecycle, capability, configuration, or Workspace availability behavior.

## Requirements

### REQ-1. Bootstrap without Azents-issued deployment credentials

A trusted Platform Kubernetes Provider deployment must be fully declarable before Azents and its database are available, without requiring an Azents-issued Provider credential.

**Acceptance criteria**

- Rendering and applying the trusted Platform Kubernetes Provider deployment requires no Provider credential value from Azents or an external secret store.
- Provider bootstrap does not run a Job that reads Azents database-backed credential state or writes a Provider credential Secret.

### REQ-2. Authentication follows the trust boundary

Trusted Platform bootstrap Providers and Workspace Providers must be able to use different authentication methods appropriate to their trust boundaries.

**Acceptance criteria**

- The trusted Platform Kubernetes Provider authenticates through its Kubernetes workload identity.
- A Workspace Provider continues to authenticate with an Azents-issued token.
- Selecting one method never causes Control to try another method after verification failure.

### REQ-3. Authenticated Provider identity binding

Runtime Control must derive Provider identity from a successfully authenticated server-known binding rather than a registration payload.

**Acceptance criteria**

- A valid workload identity or Azents-issued token resolves to exactly one durable Provider ID.
- A registration that claims a different Provider ID is rejected.
- The opaque `system-kubernetes` Provider ID remains unchanged.

### REQ-4. No operator-managed Provider secret

The trusted Platform Kubernetes Provider must not require a dedicated Kubernetes Secret or external-secret entry for Runtime Control authentication.

**Acceptance criteria**

- The Helm chart has no required Provider credential Secret for the trusted Platform Kubernetes Provider path.
- Home contains no PushSecret, ExternalSecret, or Infisical key reference for a Kubernetes Provider credential.
- The long-running Provider ServiceAccount has no Secret-write permission.

### REQ-5. Runtime-bound Runner authentication

A Runtime Runner connection must authenticate as one current logical Runtime incarnation without a deployment-wide operator-managed shared token.

**Acceptance criteria**

- The authenticated credential determines the Runtime identity and incarnation accepted by Control.
- A credential issued for one Runtime or desired generation cannot authenticate another Runtime or generation.
- Home does not require an additional Infisical secret for Runtime Runner authentication.

### REQ-6. Fail-closed connection handling

Provider and Runner authentication must fail closed without payload identity trust or authentication-method fallback.

**Acceptance criteria**

- Missing, invalid, expired, stale, or mismatched authentication is rejected before the connection is registered.
- Provider credentials, workload tokens, and Runner credentials are not written to logs, rendered manifests, diagnostics, or committed files.
- Provider, Runner, and sandbox-control credentials remain separate security boundaries.

### REQ-7. Deployment recovery ordering

Home must not deploy manifests that expect the new authentication behavior until a compatible immutable Azents snapshot is available.

**Acceptance criteria**

- The Azents recovery PR is verified before Home snapshot references are updated.
- Home removes obsolete Secret resources and values atomically with the compatible chart and image snapshot update.
- No live-cluster write is performed without explicit requester approval.

### REQ-8. Durable binding lifecycle and Admin management

Provider authentication bindings must be durable resources that Platform Admins can inspect and manage without exposing credential plaintext.

**Acceptance criteria**

- Admin inventory identifies the Provider, authentication method, bound subject, lifecycle state, ownership source, connection health, and relevant timestamps.
- Admin-authorized binding creation, rotation, and revocation preserve the Provider's opaque identity.
- Revoking a binding prevents it from opening or retaining Provider command authority.
- Bootstrap-owned bindings are distinguishable from Admin-owned bindings and cannot be silently replaced by a conflicting subject.
- Binding lifecycle changes produce metadata-only audit events.

### REQ-9. Extensible normalized authentication contract

Provider authentication implementations must return one normalized authenticated identity and share connection authorization behavior without sharing method-specific credentials.

**Acceptance criteria**

- Adding another method does not require changing Provider identity, registration payload authority, or durable connection semantics.
- Method-specific evidence and configuration remain isolated behind the selected verifier.
- Unknown methods and method/configuration mismatches fail closed.
- Long-running connections cannot retain authority after the authenticated binding, credential, or verified workload evidence expires or is revoked.

## Fixed Constraints

- Runtime and sandbox containers must never receive a host Docker socket.
- No generic `privileged: true` Admin opt-in may be introduced.
- Provider, Runner/control, and sandbox-control credentials must remain separate.
- Provider identity must never be accepted from an unauthenticated payload.
- Authentication methods must not fall back to another method after failure.
- The `system-kubernetes` Provider ID remains opaque and stable.
- Executed database migrations are immutable; any schema change requires a new revision and revision pointer update.
- Plaintext credentials must never be committed.
- The complete durable binding model and Admin management surface are part of this delivery, not deferred cleanup.

## Open Assumptions

- The first trusted workload-identity deployment runs in a Kubernetes trust boundary where Runtime Control can validate the Provider ServiceAccount identity.
- Additional workload identity providers and cross-cluster trust models will extend the normalized binding contract in future snapshots.

## Confirmation

Confirmed by the requester on 2026-07-23 through the instructions to correct the accumulated Provider and Runtime Control authentication requirements, treat the current state as a deployment-blocking incident, implement through the documented ideal authentication stage, and finish with clean branches rebased on the latest `main` and passing CI.
