---
title: "Bound Runtime Control Connections Phase 4 Execution Plan"
created: 2026-07-23
tags: [implementation, runtime, admin, authentication, frontend]
document_role: supporting
document_type: supporting-plan
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Phase 4 Execution Plan

## Phase Execution Plan

- Phase: `4 — Admin product surface`
- Branch/base: `feature/runtime-control-auth-06-admin-surface` → `feature/runtime-control-auth-05-runner-auth`
- PR boundary: System Admin authentication-binding inventory, detail, create, rotate, revoke, audit, binding-scoped enrollment authority, generated Admin clients, and Runtime Provider detail UI
- Inputs: Phase 1 durable binding/audit aggregate and optimistic `admin_version`; Phase 2 binding-derived Provider authority and retained-connection revocation; Phase 3 Runner authentication PR #818
- Deliverables: Secret-safe Admin binding lifecycle service and API; provider-scoped binding inventory; metadata-only audit history; one-time enrollment grant issuance for Admin-owned issued-token bindings; bootstrap ownership restrictions; generated Python and TypeScript Admin clients; existing Runtime Provider detail UI Authentication section with safe actions and one-time-secret handling
- Non-goals: New Provider authentication methods, Kubernetes projected-token or TokenReview RBAC rendering, Helm values/templates, Home manifests or deployment, Runtime/Provider protocol behavior, E2E evidence, living-spec promotion, and cleanup
- Interfaces: `GET /runtime-provider/v1/providers/{provider_id}/authentication-bindings`; `GET /runtime-provider/v1/authentication-bindings/{binding_id}`; `POST /runtime-provider/v1/providers/{provider_id}/authentication-bindings`; `POST /runtime-provider/v1/authentication-bindings/{binding_id}/rotate`; `POST /runtime-provider/v1/authentication-bindings/{binding_id}/revoke`; `GET /runtime-provider/v1/authentication-bindings/{binding_id}/audit-events`. Mutations use `expected_admin_version`; create and rotate support only Admin-owned `azents_issued_token`; rotate returns one enrollment grant secret exactly once; bootstrap-owned and Kubernetes ServiceAccount bindings are read-only; responses never include verifiers, credential secrets, projected tokens, encrypted values, or Runner evidence.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Binding Admin domain and persistence | `phase4-binding-admin-domain` | `python/apps/azents/src/azents/services/runtime_provider_binding_admin/**`; `python/apps/azents/src/azents/repos/runtime_provider_binding/**`; narrowly required `runtime_provider_control` repository/service paths and tests | Existing binding, credential, connection, and audit rows | Provider-checked list/detail/create; optimistic rotate/revoke; binding-scoped grant issuance; credential/connection authority cascade; metadata-only audit | Backend Ruff/format/Pyright; focused service/repository tests with PostgreSQL fixtures |
| Admin API and schemas | `phase4-binding-admin-api` | `python/apps/azents/src/azents/api/admin/runtime_provider/v1/**`; `python/apps/azents/src/azents/api/admin/runtime_provider_enrollment/v1/**` | Fixed service errors and one-time response contract | System Admin protected routes, 201/404/409/422 mapping, redacted list/detail/audit projections, no provider-ID fallback | Route tests, OpenAPI dump, redaction and stale-version tests |
| Generated Admin clients | Root agent via `openapi-client-gen` | Generated Python and TypeScript Admin client packages and specifications only | Stable Admin OpenAPI routes and schemas | Regenerated clients with binding lifecycle models and operations; no manual generated edits | Generator checks, Python client checks, TypeScript format/lint/typecheck/build |
| Admin Web integration | Root agent | `typescript/apps/azents-admin-web/src/trpc/routers/**`; `src/features/runtime-providers/**`; minimal router registration and colocated tests/stories | Generated TypeScript Admin client | Authentication section inside existing Provider detail; inventory/detail/audit; bootstrap read-only state; create/rotate/revoke actions; one-time secret modal cleared on close | Component/container tests, accessibility states, secret-cache assertions, TypeScript format/lint/typecheck/build |

- Integration order: Implement and test binding Admin service/repository semantics; expose stable Admin routes and dump OpenAPI; regenerate both Admin clients; add tRPC wrappers and UI against generated operations; run cross-layer redaction, optimistic-conflict, and one-time-secret tests.
- Final validation: Backend affected Ruff/format, full Pyright, focused repository/service/route tests, OpenAPI dump and generated-client drift; Python Admin client checks; TypeScript format/lint/typecheck/build and focused Admin Web tests; `git diff --check`; scans proving secret fields are absent from query projections, audit metadata, logs, tRPC query caches, and browser storage.
- Scope-drift check: Compare `git diff --name-only feature/runtime-control-auth-05-runner-auth...HEAD` against the owned paths. Move Helm/RBAC, Home, Provider/Runner protocol behavior, E2E reports, spec promotion, and cleanup to their later phases before commit.

## Fixed Phase 4 Contracts

- Admin binding routes are binding-authoritative. Provider IDs scope inventory and creation but never select an existing binding for mutation.
- Create supports only an Admin-owned `azents_issued_token` binding. `kubernetes_service_account`, bootstrap ownership, subject replacement, and method mutation are rejected.
- Rotate requires an active Admin-owned issued-token binding and the current `admin_version`. It advances the version, appends a metadata-only `rotated` audit event, and returns a newly issued enrollment grant secret once. Existing credentials remain authoritative until separately superseded by deployment or the binding is revoked.
- Revoke requires the current `admin_version`, records actor/reason metadata, revokes active credential authority for the binding, disconnects retained Provider connections, and appends a metadata-only `revoked` audit event.
- Stale optimistic mutations return a bounded conflict response with the current safe binding projection; missing Provider or binding returns not found; unsupported owner/method/state returns conflict; invalid expiry or input returns validation failure.
- List, detail, health, and audit responses include only safe binding, lifecycle, ownership, timestamps, connection-health, revocation, and method-specific non-secret configuration fields.
- The old provider-ID Admin enrollment-grant route and global Admin credential-revoke route are replaced rather than retained as legacy fallbacks.
- The existing public grant exchange route remains path-compatible and continues its one-time credential return contract; it resolves authority from the grant's durable `binding_id`.
- The Admin Web preserves the existing Runtime Provider master-detail and responsive Drawer layout. Binding secrets exist only in mutation response state, are never placed in query caches or browser storage, and are cleared when the one-time modal closes.

## Completion Gate

Phase 4 is complete only when:

1. System Admins can list and inspect safe binding lifecycle, ownership, health, and metadata-only audit history for one Provider.
2. Admin-owned issued-token binding create, rotate, and revoke paths enforce method, owner, state, Provider consistency, and optimistic version contracts.
3. Rotate returns an enrollment grant secret once without persisting or logging plaintext; list/detail/audit routes cannot return it.
4. Revocation removes credential and retained-connection authority for the binding while preserving Provider identity and audit history.
5. Bootstrap-owned and Kubernetes ServiceAccount bindings render read-only and reject Admin mutation.
6. Python and TypeScript Admin clients are regenerated from the authoritative OpenAPI document.
7. The existing Runtime Provider detail page exposes Authentication inventory/detail/actions without changing its Provider list/detail layout.
8. Backend and frontend quality gates pass, the phase commit is created, and the stacked PR is opened before Helm integration begins.
