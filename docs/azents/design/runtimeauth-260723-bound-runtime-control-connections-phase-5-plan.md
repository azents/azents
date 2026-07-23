---
title: "Bound Runtime Control Connections Phase 5 Execution Plan"
created: 2026-07-23
tags: [implementation, runtime, authentication, helm, kubernetes]
document_role: supporting
document_type: supporting-plan
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Phase 5 Execution Plan

## Phase Execution Plan

- Phase: `5 — Helm workload identity and secret-free deployment path`
- Branch/base: `feature/runtime-control-auth-07-helm-workload-identity` → `feature/runtime-control-auth-06-admin-surface`
- PR boundary: Azents Helm chart and Kubernetes Runtime Provider deployment integration for projected ServiceAccount authentication
- Inputs: Phase 2 explicit `kubernetes_service_account` verifier and TokenReview support; Phase 3 Runtime-bound Runner authentication; Phase 4 durable Admin binding lifecycle
- Deliverables: Projected ServiceAccount token with audience `azents-runtime-control`; typed bootstrap authentication declaration; Runtime Control TokenReview RBAC; Provider token-file rotation reconnect; removal of Provider credential Secret/bootstrap resources and shared Runtime Control token values; updated chart schema, documentation, and regression tests
- Non-goals: Home manifests or snapshot changes, live deployment, living-spec promotion, Runtime storage migration, additional authentication methods, Provider/Runner protocol redesign, and cleanup outside obsolete authentication resources
- Fixed security boundary: Runtime Control may call TokenReview. The long-running Kubernetes Provider may manage Runtime Pods/PVCs and its leader Lease, but receives no Secret-write or TokenReview permission.
- Storage safety: The chart must not render, own, select, delete, rename, or recreate Runtime PVCs as part of authentication rollout. Existing dynamic Runtime PVC/PV identity remains unchanged.

| Workstream | Owned paths | Output | Validation |
| --- | --- | --- | --- |
| Provider workload identity | `python/apps/azents-runtime-provider-kubernetes/**` | Required ServiceAccount token-file setting, explicit KSA auth method, reconnect after projected-token rotation, bounded errors without token logging | Ruff, Pyright, full Provider tests |
| Helm authentication path | `infra/charts/azents/**` | Projected token volume/env, typed bootstrap binding metadata, TokenReview RBAC for Runtime Control, obsolete Secret/bootstrap resources removed | Schema validation, render tests, Helm lint/template when available |
| Storage and privilege regression | Chart tests and Kubernetes Provider tests | No Docker socket, generic privileged mode, Secret-write permission, TokenReview permission on Provider, or Runtime PVC ownership/deletion path | Focused negative render assertions and existing PVC reuse tests |

## Fixed Phase 5 Contracts

- The projected ServiceAccount token audience is exactly `azents-runtime-control`.
- The token is mounted at a dedicated read-only path and passed through `AZ_RUNTIME_PROVIDER_SERVICE_ACCOUNT_TOKEN_FILE`.
- The Provider reads the current token immediately before connecting and reconnects after file content changes. It never logs token content.
- Bootstrap declares `kubernetes_service_account` with normalized subject, namespace, ServiceAccount name, and audience. It does not issue or persist a synthetic grant, credential, or Secret.
- Runtime Control uses the server ServiceAccount and receives only the cluster-scoped `authentication.k8s.io/tokenreviews` create permission required for TokenReview.
- `server.runtimeControl.auth` and `runtimeProviderKubernetes.credential` values, env injection, bootstrap Job, staging Secret, and bootstrap RBAC are removed rather than retained as compatibility fallbacks.
- Runtime Control TLS remains mandatory.
- The opaque Provider ID remains `system-kubernetes` by default.
- Runner authentication continues to use Runtime-bound credentials and no deployment-wide shared token.

## Completion Gate

Phase 5 is complete only when:

1. Rendering the enabled Kubernetes Provider requires no Provider credential Secret or shared Runtime Control auth Secret.
2. The Provider Deployment contains the projected token audience, token path, explicit KSA auth environment, and no legacy credential volume/env.
3. The bootstrap ConfigMap contains the typed KSA binding declaration for the rendered Provider ServiceAccount identity.
4. Runtime Control can create TokenReview requests, while the Provider ServiceAccount cannot call TokenReview or write Secrets.
5. Obsolete credential bootstrap Job/Secret/ServiceAccount/Role/RoleBinding templates and values are absent.
6. Chart and Provider tests prove token rotation reconnect and authentication rollout cannot select or own Runtime PVCs.
7. Focused and full quality checks pass, the phase commit is created, and the stacked PR is opened before Home snapshot work begins.
