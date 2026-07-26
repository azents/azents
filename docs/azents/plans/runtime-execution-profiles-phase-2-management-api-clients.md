---
title: "Runtime Execution Profiles Phase 2 Management API and Client Execution Plan"
created: 2026-07-26
tags: [runtime, provider, api, openapi, client, security]
---

# Phase Execution Plan

- Phase: `2 — Management APIs and generated clients`
- Branch/base: `feature/runtime-execution-profiles-04-management-api-clients` → `feature/runtime-execution-profiles-03-policy-domain`
- PR boundary: System Admin Platform/Profile APIs, Workspace restriction APIs, Agent Profile-intent APIs, safe policy/audit projections, OpenAPI documents, and regenerated Admin/Public Python and TypeScript clients.
- Inputs: `runtime-260726/REQ`, `runtime-260726/ADR`, `runtime-260726/DESIGN`, `docs/azents/plans/runtime-execution-profiles-implementation-plan.md`, and Phase 1 policy-domain interfaces from PR 3/11. Phase 1 CI passed before this branch was created.
- Deliverables:
  - System Admin APIs for Platform policy and reusable Profile list/read/create/update/retire operations, including metadata-only audit projection and concurrency versions.
  - Workspace APIs for effective policy/read diagnostics and Workspace narrowing mutation, with backend-enforced OWNER/MANAGER write access and MEMBER read access.
  - Agent administration APIs for selected Profile and restrictive override read/write, with existing Agent-administration authorization boundaries and expected-version conflict handling.
  - Safe API responses that exclude Provider credentials, projected ServiceAccount tokens, secret material, and dynamic Provider configuration authority.
  - Regenerated Admin/Public OpenAPI documents and Python/TypeScript client artifacts produced only through the official generators.
  - Authorization, expected-version, safe-projection, and generated-client drift coverage.
- Non-goals:
  - No Agent Apply action, automatic convergence scan, lifecycle dispatch, desired-generation change, or target/applied snapshot promotion behavior.
  - No Runtime Control protobuf/shared-library change, Provider capability enablement, Kubernetes/Helm/NetworkPolicy change, Runner/gateway/engine behavior, or live-cluster action.
  - No hand-written Admin or Workspace frontend implementation.
  - No new execution-policy semantics, lower-layer authority expansion, raw Provider configuration exposure, or direct product-state database access from API routes.
- Interfaces:
  - Routes call policy services only; services retain expected-version, upper-bound, reserved `system-standard`, audit, and compatibility rules introduced in Phase 1.
  - API patch semantics distinguish omitted fields from explicit `null`; clearing an override is an explicit action rather than an ambiguous empty-value default.
  - Policy and audit projections are typed application-owned DTOs. Provider contract/configuration remains compatibility input, never product-policy authority.
  - The API exposes bounded reason/status information and source versions/digests only where the caller is authorized; it never serializes credentials, token files, or raw Provider secret/configuration fields.
  - Any changed Admin or Public route/schema requires OpenAPI dump followed by official generation of both Python and TypeScript clients; generated outputs are never edited manually.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Management API, authorization, OpenAPI, and generated clients | `/root/runtime-execution-implementer` | `python/apps/azents/src/azents/api/{admin,public}/**` only for new execution-policy routes/schemas/tests; `python/apps/azents/src/azents/services/runtime_execution_policy/**`; `python/apps/azents/src/azents/repos/runtime_execution_policy/**` only for minimal typed read contracts required by service-layer list/projection operations (`list_profiles`, scoped `list_audit_events`, and Workspace-allowed Profile lookup if required); existing authorization/dependency/wiring paths only where required; dumped OpenAPI artifacts; `python/libs/azents-{admin,public}-client/**` generated outputs; `typescript/packages/azents-{admin,public}-client/**` generated outputs; associated tests | Phase 1 policy service and persistence interfaces | Backend management surfaces, safe projections, official generated clients, and tests | Backend Ruff/format/Pyright/pytest; OpenAPI dump; official Python/TypeScript generation; client type/quality checks; `git diff --check` |
| Integration and phase documents | `/root` | `docs/azents/plans/runtime-execution-profiles-phase-2-management-api-clients.md`; localized integration/review fixes only after owner report | Implementer output | Complete phase contract, scope verification, PR creation | Plan/diff scope check, primary verification, independent review recheck |

- Integration order:
  1. The implementation owner reads existing Admin/Public route, authorization, expected-version, OpenAPI, and client-generation conventions before edits.
  2. Define typed API DTOs and authorization matrix tests around the Phase 1 service contracts.
  3. Implement System Admin, Workspace, and Agent management routes through services; retain all domain validation in the service layer.
  4. Add safe compatibility/audit/effective-policy projections and expected-version conflict handling.
  5. Dump OpenAPI, regenerate all required Python and TypeScript clients through official commands, and add generation/drift checks.
  6. Run focused then relevant backend/client quality suites.
  7. Continue the independent reviewer on the complete Phase 2 diff; apply accepted localized findings, re-run affected checks, and request reviewer recheck.

- Independent review: `/root/runtime-execution-reviewer` reviews the completed Phase 2 diff against `runtime-260726/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-8`, and `runtime-260726/ADR-D1`, `D2`, `D4`, `D6`, and `D10`. Required criteria: authorization matrix enforcement in backend rather than UI, expected-version atomicity, typed safe projections without credentials or raw Provider authority/configuration, restrictive-only mutation preservation, reserved Standard guards, route/service/repository layering, and official generated-client provenance. Inputs are the approved core docs, the multi-phase plan, this plan, Phase 1 API/service contracts, and the final branch diff. Output is blocker/P1/P2 findings only.

- Final validation:
  - `git diff --check`
  - `cd python/apps/azents && uv run ruff check .`
  - `cd python/apps/azents && uv run ruff format --check .`
  - `cd python/apps/azents && uv run pyright .`
  - Focused API/service authorization and expected-version pytest suites, then affected/full backend pytest.
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py`
  - `cd python/libs/azents-admin-client && make generate`
  - `cd python/libs/azents-public-client && make generate`
  - `cd typescript && pnpm run generate --filter=@azents/admin-client`
  - `cd typescript && pnpm run generate --filter=@azents/public-client`
  - Relevant generated-client type/quality checks and pre-commit on commit.

- Scope-drift check: Compare the complete Phase 2 diff against `feature/runtime-execution-profiles-03-policy-domain`. Reject Agent Apply/convergence/lifecycle dispatch, protobuf/runtime-control, Provider, Kubernetes/Helm/NetworkPolicy, Runner/gateway/engine, live-cluster, and hand-written product UI changes. Confirm every changed executable path belongs to the implementation workstream, every new write path has backend authorization and expected-version coverage, and every generated client change follows an OpenAPI dump plus official generator invocation.
