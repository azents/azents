---
title: "Bound Runtime Control Connections Validation Report"
created: 2026-07-23
tags: [validation, runtime, authentication, security, infra]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: runtimeauth-260723
---

# Bound Runtime Control Connections Validation Report

## Conclusion

The deterministic Azents implementation stack passes backend, migration-graph, Runtime, Provider, Admin Web, generated-client, Helm, Docker-build, and GitHub CI validation. No blocker, P1, or P2 implementation defect remains in the validated Azents scope.

The complete `runtimeauth-260723` delivery is not yet eligible for the `implemented` snapshot marker. Home compatible-snapshot changes, live Kubernetes TokenReview, and before/after Runtime PVC UID, bound-PV, and data-sentinel validation remain external rollout prerequisites. No live Kubernetes write was performed because the requester has not approved a concrete deployment operation.

## Validated Stack

| Order | PR | Phase | Successful checks | Skipped checks | Non-successful checks |
| --- | ---: | --- | ---: | ---: | ---: |
| 1/10 | #808 | Design baseline | 7 | 7 | 0 |
| 2/10 | #809 | Implementation plan | 7 | 7 | 0 |
| 3/10 | #813 | Authentication binding foundation | 21 | 3 | 0 |
| 4/10 | #816 | Explicit Provider authentication | 21 | 3 | 0 |
| 5/10 | #818 | Runtime-bound Runner authentication | 21 | 3 | 0 |
| 6/10 | #823 | Admin product surface | 22 | 2 | 0 |
| 7/10 | #824 | Helm workload identity | 21 | 3 | 0 |

The #824 run includes passing deterministic E2E, Python E2E aggregation, Helm v4.2.3 lint/render tests, backend and Runtime project tests, pre-commit, TypeScript gating, and all affected Docker image builds.

## Local Deterministic Validation

### Backend and migration graph

Run from `python/apps/azents`:

| Validation | Result |
| --- | --- |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed; 1,264 files already formatted |
| `uv run pyright` | Passed; 0 errors, 0 warnings, 0 information messages |
| `uv run pytest` | Passed; 2,290 passed, 527 skipped, 5 warnings |
| Admin Provider binding routes/service/repository | Passed; 34 passed, 7 skipped |
| Provider credential/auth/bootstrap/migration preflight | Passed; 87 passed |
| Runner credential/auth/gRPC/operations | Passed; 14 passed, 5 skipped |

The migration graph contains 251 parsed revisions and exactly one head, `2743073ba95b`. `db-schemas/rdb/revision` points to that head, whose down revision is `ae769da63fed`. No executed migration was modified.

`alembic current` could not complete because the validation worktree did not contain the live database and runtime-secret settings required to construct application settings. No value was printed. Static revision parsing, migration preflight tests, and one-head validation passed; live database state remains an external prerequisite.

### Runtime libraries and applications

Each project passed `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`, and `uv run pytest -q`.

| Project | Tests |
| --- | ---: |
| `python/libs/azents-runtime-control` | 120 passed |
| `python/apps/azents-runtime-runner` | 49 passed |
| `python/apps/azents-runtime-provider-docker` | 17 passed |
| `python/apps/azents-runtime-provider-kubernetes` | 45 passed |
| **Total** | **231 passed** |

The Kubernetes Provider suite includes projected-token rotation, rejection of the legacy credential-file fallback, explicit `kubernetes_service_account` method selection, Pod replacement with the same PVC, and proof that credential-driven replacement deletes no PVC. PVC deletion remains limited to explicitly requested reset and terminal-delete behavior.

### Admin Web and generated clients

Environment: Node.js 24.18.0 and pnpm 11.1.0.

| Validation | Result |
| --- | --- |
| `pnpm install --frozen-lockfile` | Passed |
| `pnpm run generate` plus generated-client diff check | Passed; no Admin/Public client drift |
| `pnpm run format:check` | Passed; 5/5 tasks |
| `pnpm exec turbo run lint --force` | Passed; 5/5 tasks |
| `pnpm exec turbo run typecheck --force` | Passed; 7/7 tasks |
| `pnpm exec turbo run build --force` | Passed; 7/7 tasks |

The only notice was the existing non-failing `@hey-api/openapi-ts` deprecation notice for `output.format`.

### Helm and rendered security boundary

| Validation | Result |
| --- | --- |
| Helm v3.17.3 chart tests | 28 passed |
| Helm v4.2.3 chart tests | 28 passed |
| Helm v4.2.3 lint | 1 chart linted, 0 failed |
| Strict bootstrap document parsed by `HelmFileRuntimeProviderBootstrapAdapter` | Passed |
| Enabled Runtime Control and Kubernetes Provider render | 38 YAML documents parsed successfully |

The first #824 Helm CI run exposed only a version-specific schema error-message assertion: Helm v3 used `Additional property ...`, while Helm v4 used `additional properties '...'`. Commit `bfa49c26` made the test assert the semantic rejection instead of one Helm version's wording. Both Helm versions and the rerun CI passed.

## Security and Storage Invariants

| Invariant | Evidence | Result |
| --- | --- | --- |
| Authentication method is explicit and never falls back | Provider server/verifier tests; Kubernetes Provider explicit-method test; legacy credential-file fallback rejection | Passed |
| Provider identity comes from a non-null durable binding | Binding repository/service and Provider control tests; registration mismatch tests | Passed |
| Kubernetes audience is exactly `azents-runtime-control` | TokenReview tests, Helm projection, bootstrap parser cross-check | Passed |
| Provider ServiceAccount cannot review tokens or write Secrets | Provider RBAC render inspection and negative chart tests | Passed |
| Runtime Control can only create TokenReviews | ClusterRole render inspection; create-only rule and server ServiceAccount binding | Passed |
| Provider, Runner, and sandbox-control credentials remain separate | Runtime source scan and Provider/Runner environment tests | Passed |
| No active shared Runtime Control token or Provider credential Secret path | Runtime source scan; strict Helm schema rejection; obsolete Job/template removal | Passed |
| No credential plaintext enters logs, manifests, fixtures, or Git | Structured logging inspection, redaction tests, rendered manifest scan | Passed |
| No host Docker socket or generic privileged workload | Chart and Runtime source/render scans | Passed |
| Authentication rollout does not render, own, or select Runtime PVC/PV resources | Chart negative tests and rendered manifest scan | Passed |
| Credential-driven Runtime Pod replacement reuses the same PVC | Kubernetes Provider deterministic replacement tests | Passed |
| Reset/terminal delete remain the only PVC deletion paths | Kubernetes Provider lifecycle tests | Passed |

## Requirements Traceability

| Requirement | Deterministic Azents evidence | Status |
| --- | --- | --- |
| REQ-1 Bootstrap without Azents-issued deployment credentials | Secret-free Helm projection, no bootstrap Job, typed bootstrap binding | Passed |
| REQ-2 Authentication follows trust boundary | KSA and issued-token verifier suites; no fallback tests | Passed |
| REQ-3 Authenticated Provider identity binding | Durable binding, TokenReview subject resolution, registration mismatch rejection, stable `system-kubernetes` render | Passed |
| REQ-4 No operator-managed Provider secret | Azents chart and Provider RBAC satisfy the requirement | **Azents passed; Home Secret/ExternalSecret removal pending** |
| REQ-5 Runtime-bound Runner authentication | Signed Runtime/desired-generation tests, Provider injection, shared-token removal | **Azents passed; Home no-new-secret assertion pending** |
| REQ-6 Fail-closed connection handling | Provider/Runner negative matrices, expiry/revocation authority tests, secret scans | Passed |
| REQ-7 Deployment recovery ordering | Azents implementation stack and immutable-snapshot ordering preserved | **Home snapshot update and live write approval pending** |
| REQ-8 Durable binding lifecycle and Admin management | Migration/domain/API/UI/client/audit/revocation tests | Passed |
| REQ-9 Extensible normalized authentication contract | Explicit verifier registry, normalized binding result, connection authority tests | Passed |
| REQ-10 Non-destructive Runtime storage rollout | Migration and Provider deterministic PVC-preservation evidence | **Deterministic passed; live PVC UID/PV/sentinel comparison pending** |

No open item above is an unresolved Azents implementation defect. The pending items are intentionally ordered Home and live-environment acceptance criteria.

## ADR Conformance

| Decision | Result |
| --- | --- |
| ADR-D1 explicit single-method selection | Conformant |
| ADR-D2 Kubernetes TokenReview workload identity | Conformant |
| ADR-D3 separate Azents-issued token method | Conformant |
| ADR-D4 first-class durable authentication bindings | Conformant |
| ADR-D5 Runtime-bound Runner credential | Conformant |
| ADR-D6 remove active operator-managed authentication Secrets | Conformant in Azents; Home pruning pending |
| ADR-D7 complete extensible binding foundation | Conformant in the implementation stack |
| ADR-D8 preserve Runtime storage identity | Deterministically conformant; live rollout evidence pending |

## Living-Spec Drift

The current living specs intentionally remain unchanged in this validation PR and require promotion in PR 9/10.

| Spec | Drift found |
| --- | --- |
| `docs/azents/spec/domain/runtime-provider.md` | Deployment boundary still describes the credential bootstrap Job, staging/final Provider Secrets, credential-file watch, and source-owned credential rotation instead of KSA bindings and Admin binding lifecycle. Its `code_paths` also omit the new binding model/repository/Admin API paths. |
| `docs/azents/spec/flow/agent-runtime-control.md` | Control Stream Authentication still describes the optional shared Runner token and existing-Secret Helm paths. It does not describe explicit Provider method dispatch, TokenReview evidence expiry, durable binding authority, or Runtime/desired-generation Runner credentials. |

## External Prerequisites and Skips

- **Live database migration state:** blocked by absent database/application-secret settings in the validation worktree. Static one-head and migration preflight evidence passed.
- **Live Kubernetes TokenReview:** not run. A writable Kubernetes validation environment and explicit requester approval are required.
- **Live Runtime storage preservation:** not run. Before/after PVC name, UID, bound PV, and data-sentinel evidence requires the compatible deployment and explicit requester approval.
- **Home compatible snapshot:** not prepared in this PR. It begins only after the final Azents stack is rebased, validated, and available as one immutable snapshot.

## Scope-Drift Result

The validation branch contains only this phase plan, this report, and any responsible earlier-phase correction discovered by validation. The Helm v3/v4 correction was committed to Phase 5 and the validation branch was rebased onto it. No living spec, implemented date, Home manifest, Kubernetes resource, or unrelated product behavior was changed in this PR.
