---
title: "Bound Runtime Control Connections"
created: 2026-07-23
updated: 2026-07-23
tags: [architecture, runtime, provider, security, infra]
document_role: primary
document_type: adr
snapshot_id: runtimeauth-260723
---

# runtimeauth-260723/ADR: Bound Runtime Control Connections

## Requirements

This ADR records the architecture decisions for the confirmed [Bound Runtime Control Connections Requirements](../requirements/runtimeauth-260723-bound-runtime-control-connections.md) (`runtimeauth-260723/REQ`).

The current deployment is blocked by authentication material that cannot be produced before Azents is available. Recovery speed is a primary delivery constraint, but the recovery change must preserve the target security model and must not introduce a legacy fallback.

## Context

The implemented Provider path authenticates every Provider through an Azents-issued opaque credential. Trusted Helm bootstrap therefore creates a database-backed enrollment grant and credential, writes the credential to a staging Secret, and expects deployment automation to persist and rematerialize it. This contradicts the requirement that trusted bootstrap be fully preparable before Azents and its database are available.

Runtime Runner streams use a separate deployment-wide shared Runtime Control token. The token is a transport admission gate and does not bind the authenticated connection to the registration payload's Runtime ID or desired generation.

The existing Provider credential implementation already establishes an important invariant: a verified credential resolves a durable Provider identity before registration claims are accepted. The new authentication paths must preserve that invariant.

## Ideal Goal and Delivery Boundary

The architecture has an extensible authentication-method resolver and durable authenticated bindings. Each method verifies its own evidence and returns one normalized authenticated identity. Provider and Runner registration claims are consistency checks only. Binding lifecycle, audit, revocation, health, and Admin management are part of this delivery.

The delivery implements the methods currently required to unblock Home safely:

- Kubernetes ServiceAccount workload identity for the trusted bootstrap Platform Kubernetes Provider;
- the existing Azents-issued opaque token for Workspace and manually enrolled Providers; and
- a Runtime-bound signed credential for Runtime Runners.

It also implements the generic durable binding aggregate, Admin API/UI, lifecycle and audit, and reusable verifier composition required for additional methods to extend the model later. Additional workload identity implementations and cross-cluster trust policies are future extensions, not missing foundations.

## Decisions

### runtimeauth-260723/ADR-D1. Select exactly one explicit authentication method

Every Provider and Runner control connection uses one explicit authentication method. Runtime Control dispatches to only that verifier and rejects failure without trying another method.

Authentication evidence determines identity. Registration `provider_id`, `runtime_id`, credential identifiers, scope, and generation claims cannot grant authority and are accepted only when consistent with the authenticated identity.

**Rejected alternatives**

- Guessing the method from token shape.
- Trying an Azents-issued credential after Kubernetes verification fails, or the reverse.
- Trusting a registration payload to select its own Provider or Runtime binding.

### runtimeauth-260723/ADR-D2. Use Kubernetes TokenReview for trusted Platform bootstrap

The trusted Platform Kubernetes Provider presents a projected ServiceAccount token with a Runtime Control-specific audience. Runtime Control calls Kubernetes TokenReview and accepts only an authenticated result with the required audience and exact ServiceAccount subject.

The verified Kubernetes username is matched against a durable bootstrap-owned Provider authentication binding. The binding resolves the opaque durable Provider ID; the Provider registration payload does not choose it. The binding is declared through the Helm bootstrap Provider declaration and reconciled into the same binding aggregate managed by the Admin surface. Runtime Control receives TokenReview permission; the Provider ServiceAccount does not.

The long-running Provider watches token rotation and reconnects with the replacement projected token.

**Rejected alternatives**

- Minting an Azents credential during bootstrap and exporting it through a Secret store.
- Giving the Provider permission to review its own token.
- Mapping every Kubernetes Provider kind automatically to `system-kubernetes` without a subject binding.
- Using TLS client identity as an implicit Provider identity in this recovery.

### runtimeauth-260723/ADR-D3. Preserve Azents-issued Provider tokens as a separate method

The existing enrollment grant and Provider credential lifecycle remains the authentication method for Workspace Providers and manually enrolled Providers outside the trusted Kubernetes bootstrap boundary.

Its verifier-backed credential record remains the authenticated binding to one durable Provider. Kubernetes ServiceAccount authentication does not fall back to this method and does not create a synthetic enrollment credential.

### runtimeauth-260723/ADR-D4. Make authentication bindings first-class durable resources

Every Provider control authentication method resolves one durable authentication binding before registration. A binding records the Provider, method, normalized subject, lifecycle, ownership source, method configuration, audit timestamps, and revocation state.

Azents-issued credentials belong to an `azents_issued_token` binding. Kubernetes ServiceAccount identity belongs to a `kubernetes_service_account` binding. Credentials remain method-specific evidence and do not replace the binding aggregate.

Durable Provider connection state references the authenticated binding and records the authenticated subject and evidence expiry. An Azents credential reference is present only for the issued-token method. No synthetic credential, grant, or Secret record represents Kubernetes workload identity.

Admin APIs and UI expose safe binding inventory, creation where authorized, rotation, revocation, ownership, health, and audit without returning credential plaintext.

### runtimeauth-260723/ADR-D5. Replace the shared Runner token with a Runtime-bound signed credential

Runtime Control derives a domain-separated signing key from the existing credential-encryption root and issues a signed Runner credential containing the logical Runtime ID and desired generation.

The Runner presents the credential as gRPC metadata. Runtime Control verifies the signature, resolves identity from the verified claims, loads the durable Runtime, and requires the claimed desired generation to equal the current durable desired generation before registering the stream. A mismatched registration Runtime ID is rejected.

The credential is valid only for the bound Runtime desired generation. Connection generation fencing remains a separate mechanism for replacing physical Runner streams.

**Rejected alternatives**

- Keeping the deployment-wide shared Runner transport token.
- Treating `runtime-runner:{runtime_id}:{generation}` as a secret.
- Accepting the registration's `runtime_id` after only transport-level authentication.
- Storing one Runner secret per Runtime in Infisical or Kubernetes Secrets.

### runtimeauth-260723/ADR-D6. Remove operator-managed authentication Secrets from the active deployment

The recovery deployment requires no Provider credential Secret and no shared Runtime Control Runner Secret. Runtime Control TLS remains mandatory and separate.

The Helm credential-bootstrap Job, staging Secret, Provider credential volume, shared Runtime Control auth values, and their Home references are removed from the active path. Existing stale Secret resources are pruned only as part of the coordinated compatible snapshot rollout, with prune ordering configured so replacement workloads become healthy first.

### runtimeauth-260723/ADR-D7. Complete the extensible binding foundation in this delivery

The PR stack includes the durable binding aggregate, the two Provider methods, connection lifecycle, Admin API/UI, Runtime-bound Runner authentication, chart integration, migrations, generated clients, tests, specs, and safe Home rollout.

The implementation provides a reusable method contract and explicit connection-expiry handling so additional methods do not require another control-domain rewrite. The current delivery does not need to implement authentication methods other than Kubernetes ServiceAccount and Azents-issued token, nor cross-cluster issuer policy.

## Consequences

- Trusted Kubernetes bootstrap no longer depends on Azents-issued secret material.
- Workspace Provider enrollment remains available without sharing Kubernetes trust assumptions.
- Provider and Runner identities are resolved before registration.
- The Runtime Control server gains a narrow cluster-scoped TokenReview permission.
- Provider authentication bindings and binding-backed connection persistence require forward migrations.
- Server, Provider, Runner, chart, and Home snapshot changes must be deployed as one compatible cutover.
- The Admin surface grows a safe authentication-binding inventory and lifecycle workflow.

## Security Invariants

- Provider, Runner, and sandbox-control credentials remain separate.
- Authentication methods never fall back.
- Payload identity never grants authority.
- The Provider ServiceAccount receives no TokenReview or Secret-write permission.
- Runtime and sandbox containers receive no Provider credential, host Docker socket, or generic privileged toggle.
- Plaintext authentication material is excluded from logs, diagnostics, rendered manifests, and Git.
