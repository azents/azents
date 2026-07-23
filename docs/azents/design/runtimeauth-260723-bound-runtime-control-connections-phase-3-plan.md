---
title: "Bound Runtime Control Connections Phase 3 Execution Plan"
created: 2026-07-23
tags: [implementation, runtime, runner, security, kubernetes]
document_role: supporting
document_type: supporting-plan
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Phase 3 Execution Plan

## Phase Execution Plan

- Phase: `3 — Runtime Runner authentication`
- Branch/base: `feature/runtime-control-auth-05-runner-auth` → `feature/runtime-control-auth-04-provider-auth`
- PR boundary: Runtime-and-desired-generation-bound Runner credentials, binding-derived Runner stream identity, durable retained authority, shared client and Runtime environment integration, shared-token removal from active Python paths, and non-destructive Runtime storage regression coverage
- Inputs: Phase 2 explicit Provider authentication and binding-derived Provider identity from PR #816; existing Runtime desired-generation lifecycle and independent coordination-store Runner generation fencing
- Deliverables: Domain-separated signed Runner credential primitive; non-secret credential identifier; durable Runtime/generation authenticator; Runner gRPC identity and retained-authority enforcement; Provider command credential issuance; Runner metadata and registration consistency checks; Docker/Kubernetes Runtime environment updates; Pod/container replacement on changed generation-bound evidence without PVC/workspace deletion
- Non-goals: Provider binding Admin API/UI, OpenAPI clients, Helm values/templates/RBAC/Secrets, Home manifests or deployment, new database schema, E2E evidence, living-spec promotion, and cleanup
- Interfaces: A versioned signed credential authenticates exactly one `runtime_id` and durable `desired_generation`; the issued result carries plaintext token plus a non-secret credential ID; the Runner sends the token only as standard Bearer metadata and sends the credential ID only as a registration consistency claim; authenticated claims determine Runtime identity; durable desired-generation authority is rechecked for retained streams; coordination Runner generation remains a separate physical-stream fence

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Credential primitive and durable authority | Root agent | `python/apps/azents/src/azents/core/runtime_runner_credential.py`; `python/apps/azents/src/azents/services/runtime_runner_auth/**`; `python/apps/azents/src/azents/repos/agent_runtime/**` only if an authority query is required; focused tests | Existing credential-encryption root and Agent Runtime desired generation | Versioned domain-separated signer/verifier, issued credential result, strict parsing/tamper/root tests, Runtime existence and current-generation authorization | Backend Ruff, Pyright, credential/service tests |
| Runner server and lifecycle integration | Root agent | `python/apps/azents/src/azents/runtime/control_protocol/grpc/{auth.py,runner_server.py,runner_server_test.py}`; `python/apps/azents/src/azents/runtime/control_protocol/{data.py,reconciler.py,reconciler_test.py}`; `python/apps/azents/src/azents/runtime/control_server.py`; related control-server tests | Credential/authenticator contract | Authenticated Runtime identity before registration, payload consistency checks, retained authority before inbound and outbound work, signed credential issuance in Provider commands, shared Runner token removal | Backend Ruff, full Pyright, focused gRPC/reconciler/control-server tests |
| Shared Runner client and Runner app | `phase3-runner-client` implementation subagent | `python/libs/azents-runtime-control/src/azents_runtime_control/grpc_runner_client.py`; `python/libs/azents-runtime-control/tests/grpc_runner_client_test.py`; `python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py`; `python/apps/azents-runtime-runner/tests/main_test.py` | Fixed Bearer token and credential-ID registration contract | Required signed-token environment, non-secret credential-ID registration, explicit Runner credential client parameter, no shared control token | Shared-library and Runner-app Ruff, format, Pyright, tests |
| Provider command and Runtime environment | `phase3-provider-runtime-env` implementation subagent | `python/libs/azents-runtime-control/src/azents_runtime_control/{provider.py,grpc_provider_client.py}` and related tests; `python/apps/azents-runtime-provider-docker/**`; `python/apps/azents-runtime-provider-kubernetes/**` | Issued credential payload contract | Parse and inject token plus credential ID, remove shared token from Runtime environments, replace stale compute when generation-bound evidence changes, preserve Docker workspace binds and Kubernetes PVC claim identity | Shared-library and both Provider app Ruff, format, Pyright, tests; explicit no-PVC-delete assertions |

- Integration order: Freeze issued credential and Provider command payload shapes; implement credential/authenticator and shared client/provider workstreams in parallel; integrate Runner server and Runtime Control wiring; run cross-project authority and storage-preservation tests.
- Final validation: Backend Ruff/format/full Pyright and focused credential/auth/gRPC/reconciler/control-server tests; runtime-control shared library Ruff/format/Pyright/tests; Runtime Runner Ruff/format/Pyright/tests; Docker and Kubernetes Provider Ruff/format/Pyright/tests; `git diff --check`; scan active Python Runtime paths for `AZ_RUNTIME_CONTROL_AUTH_TOKEN` and shared Runner-token configuration.
- Scope-drift check: Compare `git diff --name-only feature/runtime-control-auth-04-provider-auth...HEAD` against the owned paths and move Admin, OpenAPI, Helm, Home, migration, E2E-report, spec-promotion, or cleanup changes to later phases before commit.

## Fixed Phase 3 Contracts

- The credential signing key is derived from the configured credential-encryption root with a Runner-specific domain label. Provider credentials and Runner credentials cannot verify each other.
- Credentials have no wall-clock expiry or refresh loop. Authority ends when the durable Runtime is absent or its desired generation differs from the authenticated generation.
- The credential format is versioned, strictly parsed, and integrity protected. Runtime ID, desired generation, and non-secret credential ID are covered by the signature.
- The plaintext token is minted only when a retained Provider command is projected onto gRPC, then carried in the gRPC command, Runtime process environment, and Runner Bearer metadata. The coordination stream persists only its non-secret credential ID; the token is not persisted, returned in diagnostics, or logged.
- The registration `runtime_id` and `auth_credential_id` are consistency checks. Runtime Control persists and routes by authenticated Runtime identity and verified non-secret credential ID.
- Retained authority is checked before accepting Runner messages and before claiming or emitting Runner operations. Desired-generation revocation is independent of coordination-store Runner generation fencing.
- Runtime IDs embedded in state, operation-start, and operation-event messages must match the authenticated Runtime identity.
- A changed generation-bound credential may replace the Runtime Pod or container so the new Runner receives current evidence. Kubernetes replacement deletes no PVC and mounts the same deterministic claim; Docker replacement preserves the same host workspace directories.
- Only explicit pre-existing reset and terminal-delete lifecycle commands may delete a Runtime PVC. Authentication rollout and ordinary start/reconnect paths never call those destructive paths.

## Completion Gate

Phase 3 is complete only when:

1. Signed credentials pass success, tamper, malformed, root-mismatch, Runtime-mismatch, absent-Runtime, and stale desired-generation tests.
2. Registration and retained-stream authority derive Runtime identity from verified claims and fail closed on payload mismatch or generation advancement.
3. Active Python Runtime paths no longer require or inject the deployment-wide shared Runner control token.
4. Docker and Kubernetes Providers inject the signed token and non-secret credential ID without persisting or logging plaintext.
5. Kubernetes tests prove credential-driven Pod replacement performs no PVC deletion and reuses the same claim; Docker tests prove container replacement preserves workspace bind identity.
6. Backend, shared runtime-control, Runtime Runner, Docker Provider, and Kubernetes Provider quality checks pass.
7. The Phase 3 commit and stacked PR are created before Admin product-surface implementation begins.
