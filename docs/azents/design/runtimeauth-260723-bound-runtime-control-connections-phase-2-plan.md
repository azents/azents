---
title: "Bound Runtime Control Connections Phase 2 Execution Plan"
created: 2026-07-23
tags: [implementation, runtime, provider, security, kubernetes]
document_role: supporting
document_type: supporting-plan
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Phase 2 Execution Plan

## Phase Execution Plan

- Phase: `2 — Provider authentication and control`
- Branch/base: `feature/runtime-control-auth-04-provider-auth` → `feature/runtime-control-auth-03-bindings`
- PR boundary: Explicit Provider authentication-method dispatch, binding-backed issued-token and Kubernetes ServiceAccount verification, retained connection authority, Provider client metadata, and Kubernetes projected-token rotation behavior
- Inputs: Phase 1 durable binding aggregate and binding-backed Provider Control persistence from PR #813
- Deliverables: Extensible no-fallback verifier registry; exact Kubernetes TokenReview validation; issued-token verifier; explicit gRPC auth method; Provider identity derived from the authenticated binding; connection evidence expiry and revocation authority; Provider client and Kubernetes token-file rotation integration
- Non-goals: Runtime Runner credentials, Admin API or UI, Helm/RBAC/projected-volume rendering, Home deployment, E2E validation, and living-spec promotion
- Interfaces: Authentication method is selected explicitly; one verifier handles one method; the method header is `x-azents-runtime-provider-auth-method`; Kubernetes audience is exactly `azents-runtime-control`; ServiceAccount subject is `system:serviceaccount:<namespace>:<name>`; binding configuration keys are `namespace`, `service_account_name`, and `audience`; no payload Provider identity or cross-method fallback is authoritative

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Verifier composition and authority | `phase2-provider-verifiers` implementation subagent | `python/apps/azents/src/azents/services/runtime_provider_control/{provider_auth.py,data.py,service.py,service_test.py}` | Phase 1 binding and connection contracts | Issued-token and Kubernetes SA verifiers, exact TokenReview validation, registry uniqueness, retained authority checks | Ruff; full Backend Pyright; verifier/service failure matrix |
| gRPC and shared Provider client | `phase2-provider-grpc-client` implementation subagent | `python/apps/azents/src/azents/runtime/control_protocol/grpc/auth.py`; `python/apps/azents/src/azents/runtime/control_protocol/grpc/provider_server_test.py`; `python/libs/azents-runtime-control/src/azents_runtime_control/grpc_provider_client.py`; related shared-library tests | Fixed method header and verifier contract | Explicit method metadata, strict single Bearer parsing, no fallback, client propagation | Backend/shared-library Ruff, Pyright, and tests |
| Provider application integration | `phase2-provider-apps` implementation subagent | `python/apps/azents-runtime-provider-docker/**`; `python/apps/azents-runtime-provider-kubernetes/**` | Shared Provider client metadata contract | Docker issued-token declaration; Kubernetes projected-token file reading and reconnect on token rotation | App Ruff, Pyright, unit tests |
| Runtime Control integration | Root agent | `python/apps/azents/src/azents/runtime/control_server.py`; `python/apps/azents/src/azents/runtime/control_protocol/data.py`; `python/apps/azents/src/azents/repos/runtime_provider_{binding,control}/**`; `python/apps/azents/src/azents/services/runtime_provider_selection/service.py`; dependency wiring and cross-workstream integration | Verifier and client contracts | Optional in-cluster TokenReview adapter lifecycle, nullable method-specific credential references, retained connection authority/health, and binding repository injection without Runner changes | Backend Ruff, full Pyright, repository/control-server/selection tests |

- Integration order: Freeze verifier and metadata contracts; run verifier, gRPC/client, and Provider app workstreams in parallel; integrate Runtime Control TokenReview dependency injection; run cross-project validation.
- Final validation: Backend Ruff/format/full Pyright and focused auth/control tests; runtime-control shared library Ruff/format/Pyright/tests; Docker and Kubernetes Provider Ruff/format/Pyright/tests; strict no-fallback and TokenReview failure matrix; `git diff --check`.
- Scope-drift check: Move Runner authentication, Admin API/UI, Helm templates/values/RBAC, Home, validation evidence, and spec-promotion changes to their later phase branches before commit.

## Fixed Phase 2 Contracts

- The caller supplies one explicit authentication method. Unknown, missing, duplicated, or unsupported methods fail closed.
- The registry rejects duplicate verifier registrations and never attempts another method after a verifier failure.
- Issued-token authentication resolves the credential's non-null binding, validates binding/provider consistency and lifecycle, and derives Provider identity from the binding.
- Kubernetes authentication accepts only a successful TokenReview for audience `azents-runtime-control`, an unexpired JWT `exp`, an exact ServiceAccount subject, and a matching active bootstrap-owned binding configuration.
- JWT payload is used only to derive evidence expiry after TokenReview authenticates the token.
- Provider registration payload identity is checked against authenticated identity and never overrides it.
- Heartbeat and command authority require the original binding, authentication snapshots, credential state when applicable, and unexpired evidence.
- Kubernetes Provider watches the projected token file and reconnects with new evidence without a bootstrap Secret or credential exchange.

## Completion Gate

Phase 2 is complete only when:

1. The staged diff contains no Phase 3 or later paths or behavior.
2. Explicit issued-token and Kubernetes ServiceAccount authentication paths pass their success and failure matrices.
3. Unknown, missing, duplicate, mismatched, expired, revoked, and cross-method evidence fails closed.
4. Backend, shared Provider client, Docker Provider, and Kubernetes Provider Ruff, Pyright, and focused tests pass.
5. The Phase 2 commit and stacked PR are created before Runtime Runner authentication resumes.

## Rollout Dependency

- This stacked Phase 2 branch is not an independently deployable Kubernetes Provider snapshot. The Provider now requires the projected ServiceAccount token file, while the current chart still renders the issued-credential Secret path.
- Phase 5 must render `AZ_RUNTIME_PROVIDER_SERVICE_ACCOUNT_TOKEN_FILE`, the projected token volume, TokenReview RBAC, and `AZ_RUNTIME_CONTROL_KUBERNETES_TOKEN_REVIEW_ENABLED=true` before any compatible snapshot or Home rollout uses the Phase 2 Provider image.
- Do not add a legacy credential fallback to make the intermediate stack deployable. Deployment validation starts only after the Phase 5 chart boundary is complete.
