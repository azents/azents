---
title: "Hierarchical Runtime Network Restriction Phase 6 Product Surfaces Plan"
created: 2026-08-12
tags: [runtime, network, api, admin, frontend, openapi]
---

# Phase Execution Plan

- Phase: `6/8 — Product APIs and web surfaces`
- Branch/base: `feature/network-restriction-6-product` →
  `feature/network-restriction-5-helm` at `28f558114`
- PR boundary: Activate the already implemented Kubernetes Profile v3 and Workspace
  Policy v2 contracts through bounded Admin/Public API projections, regenerated
  clients, Admin Provider/Profile views, Workspace Profile controls, and Runtime
  desired/applied network status without moving policy authority into TypeScript or
  claiming packet-enforcement validation.
- Inputs: Phase 1 canonical Profile v3, Policy v2, hierarchy composition,
  compatibility, and application-impact contracts; Phase 2 Provider protocol-v3
  connection-generation diagnostics persistence and Admin service projection; Phase
  4 strict lifecycle failure/evidence behavior; Phase 5 packaged independent
  attestations and warning-only deployment diagnostics; existing optimistic Profile
  replacement, exact Workspace/Profile ownership, Runtime desired/applied slots,
  generated OpenAPI/client workflows, Admin Provider master-detail screen, Workspace
  Runtime Profile management screen, and Runtime configuration status panel.
- Deliverables: Admin infrastructure Profile request/response unions supporting
  Kubernetes v1/v2/v3 and existing Docker versions; Workspace request/response unions
  supporting Policy v1/v2; server-authored safe effective-network projections for
  selectable and Workspace Profile responses; bounded desired/applied Runtime network
  summaries containing mode, applicable domain mode, protocol summary, HTTPS
  inspection, and enforcement status; a Provider diagnostics endpoint exposing only
  the active authenticated connection generation and an explicit unavailable state;
  bounded compatibility and strict-network failure presentation; regenerated Admin
  and Public OpenAPI specifications plus generated Python and TypeScript clients;
  mode-aware Admin Kubernetes Profile editing and presentation; Admin Provider
  attestation/diagnostic presentation; Workspace `Inherit`, `Direct network`, `Proxy
  required`, and `No external network` editing constrained by the selected
  infrastructure authority; Workspace Profile and Runtime status presentation with
  localized protocol/trust limitations; focused API, service, router, form,
  presentation, component, story, and generated-contract tests.
- Non-goals: New network authority, policy composition, compatibility evaluation, or
  capability inference in TypeScript; migration of stored legacy Profiles or removal
  of v1/v2/Policy-v1 parsing and editing; new Provider diagnostics persistence or
  capability suppression; Kubernetes object names, namespaces, ClusterIPs, CA
  certificates, private keys, raw Provider diagnostics, proxy logs, or request-level
  audit data in product APIs; lifecycle, Provider reconciliation, Helm, RBAC, proxy,
  Runner, testenv, packet-enforcement, live-cluster, Living Spec, implementation-date,
  plan-cleanup, deployment, merge, or live infrastructure changes.
- Interfaces: `RuntimeInfrastructureProfileSpec` becomes the API discriminated union
  that includes Kubernetes v1/v2/v3 while retaining Docker v1/v2. Workspace API
  policy fields use the existing `WorkspaceRuntimeProfilePolicy` discriminated union.
  Effective-network projection is produced only after server parsing and
  `compose_workspace_runtime_profile`; it exposes canonical effective mode, CIDRs,
  domain mode, and domain patterns without Provider-native evidence. Runtime status
  derives a bounded network summary from each stored desired/applied configuration
  document and the existing overall configuration status; it does not become a new
  source of desired/applied truth. Admin diagnostics call the existing
  `RuntimeProviderAdminService.get_operational_diagnostics` boundary and return
  `available=false` when no active connection-generation snapshot exists. Generated
  files are changed only through the repository OpenAPI/client generation commands.
  The server remains final authority for hierarchy validation and rejects invalid
  expansion with the existing request failure boundary.
- Approved Design mechanisms: `M1`, `M2`, `M8`, `M13`
- Authority references: `network-260812/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`,
  `REQ-6`, `REQ-7`, `REQ-9`, `REQ-10`, `REQ-11`; `network-260812/ADR-D1`,
  `ADR-D2`, `ADR-D7`, `ADR-D8`; approved Design API and Product Projection,
  Observability and Operations, Failure Retry and Recovery, Security and Permissions,
  deterministic coverage, Design Authority, Removal and Replacement, and Feasibility
  sections; current Runtime Provider, Runtime Profile, Workspace, Agent Runtime, and
  API Specs.
- Design delta: `None`
- Removal obligations: Replace API schemas that expose only legacy infrastructure
  and Workspace policy versions with the approved discriminated unions while
  retaining legacy variants. Replace CIDR-only Admin and Workspace editors with
  mode-aware CIDR/domain editors and approved explanations. Replace Runtime status
  lacking effective network mode with bounded desired/applied network summaries.
  Connect the existing active-generation diagnostics service to the Admin API and
  Provider detail instead of leaving warning diagnostics inaccessible. Do not remove
  legacy persisted documents or introduce client-side composition.
- Absence verification: API/OpenAPI/generated-client tests prove v3/v2 variants are
  represented and legacy variants remain. Static TypeScript searches and form tests
  prove no effective-policy composition or capability inference exists in either web
  app. Response serialization tests prove Kubernetes names, namespaces, ClusterIPs,
  CA/private material, raw diagnostic payloads, and proxy logs are absent. Admin
  diagnostics tests prove disconnected or snapshot-free Providers return unavailable
  and stale/non-current connection generations cannot surface. UI tests prove the
  CIDR-only shape is no longer the sole editor, invalid mode-specific fields are not
  submitted, and strict limitations are presented without claiming offline or
  packet-level proof.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| API contract activation and effective projections | `/root` | `python/apps/azents/src/azents/core/runtime_profile.py`; `services/runtime_profile_admin/**`; `services/runtime_profile_workspace/**`; `api/admin/runtime_provider/v1/**`; `api/public/runtime_profile/v1/**`; focused tests | Phase 1 parsers/composition and current Profile repositories | v1/v2/v3 infrastructure union, Policy v1/v2 union, safe effective-network projection, unchanged optimistic ownership/fencing | parser/projection/route tests, OpenAPI schema inspection, sensitive-field absence assertions |
| Provider diagnostics API | `/root` | `python/apps/azents/src/azents/api/admin/runtime_provider/v1/**`; existing `services/runtime_provider_admin/**`; focused tests | Phase 2 active-generation projection | explicit current diagnostics or unavailable response with bounded warning fields | service/route tests for active, disconnected, no snapshot, generation, checked-at, warning allowlist |
| Agent Runtime status projection | `/root` | `python/apps/azents/src/azents/api/public/agent_runtime/v1/data.py`; `services/agent_runtime/lifecycle_data.py` only if a typed internal projection is required; focused tests | stored desired/applied documents and existing status | bounded desired/applied mode, domain/protocol/inspection/enforcement summary and strict failure presentation inputs | conversion/status tests and negative sensitive-field assertions |
| OpenAPI and generated clients | `/root` | dumped Admin/Public OpenAPI artifacts; `python/libs/azents-admin-client/**`; `python/libs/azents-public-client/**`; `typescript/packages/azents-admin-client/**`; `typescript/packages/azents-public-client/**` | stable backend schemas/routes | source-generated Python and TypeScript clients containing exact new unions/endpoints | repository generation commands, clean regeneration, generated package checks, consumer typecheck |
| Admin Provider and Profile surfaces | `/root` | `typescript/apps/azents-admin-web/src/features/runtime-providers/**`; `src/trpc/routers/runtimeProvider*.ts`; focused tests/stories | generated Admin client | Kubernetes v3 mode-aware editor/detail, compatibility, attestation and active diagnostic warning presentation | schema/router/form/presentation/component tests, lint/typecheck/build |
| Workspace Profile surfaces | `/root` | `typescript/apps/azents-web/src/features/runtime-profiles/**`; `src/trpc/routers/runtime-profile.ts`; locale messages and stories/tests | generated Public client and server effective projection | authority-aware Policy v2 form, legacy edit preservation, effective mode/CIDR/domain presentation, approved guidance | schema/router/container/component/story tests, locale key checks, lint/typecheck/build |
| Runtime status surface | `/root` | `typescript/apps/azents-web/src/features/chat/workspace/components/RuntimeConfigurationStatus*`; related types/locales/tests/stories | generated bounded Runtime status model | desired/applied effective network summary, enforcement/recreation/failure guidance | component/story tests and responsive/empty/error/status coverage |
| Independent review | `/root/network-260812-reviewer` | read-only stable Phase 6 diff | implementation and focused evidence | authority, privacy, compatibility, generated-contract, hierarchy, UX, removal, and scope report | written Critical/Warning finding report |

- Integration order: Activate API unions and add server-only effective projection →
  add Provider diagnostics route/schema → add bounded Runtime status projection → run
  focused backend tests → dump OpenAPI and regenerate all four clients → update Admin
  tRPC schemas and Profile/Provider surfaces → update Workspace tRPC/Profile surfaces
  and localized guidance → update Runtime status surface → run focused frontend tests
  and stories → run backend and TypeScript quality gates → perform sensitive-field,
  legacy-compatibility, no-client-composition, and scope-drift searches → independent
  review → required corrections → final stable-diff validation.
- Independent review: `/root/network-260812-reviewer` reviews read-only against the
  confirmed Requirements, ADR-D1/D2/D7/D8, approved Design `M1`/`M2`/`M8`/`M13`,
  current Specs, this plan, generated artifacts, focused evidence, and the stable
  Phase 6 diff. It reports only material findings concerning legacy contract
  preservation, discriminator correctness, server-only hierarchy authority,
  optimistic fencing/ownership, diagnostics generation freshness and warning-only
  semantics, API privacy/redaction, bounded Runtime status, unsupported Provider
  behavior, strict failure presentation, mode-aware UX, localization, generated-file
  provenance, removal completeness, or unauthorized Phase 7/lifecycle scope.
- Final validation: In `python/apps/azents`, run focused API/service tests, `uv run
  ruff check .`, `uv run ruff format --check .`, `uv run ty check
  --error-on-warning`, and the relevant full pytest suite. Run `uv run python
  src/cli/dump_openapi.py`, then in `python/libs/azents-admin-client` and
  `python/libs/azents-public-client` run `make generate` and their configured quality
  checks. In `typescript`, run `pnpm run generate
  --filter=@azents/admin-client`, `pnpm run generate
  --filter=@azents/public-client`, format/lint/typecheck for both generated packages,
  `@azents/admin-web`, and `@azents/web`, focused component/router/story tests where
  configured, and both application builds. Confirm a second regeneration is clean,
  run `git diff --check`, and run static searches for forbidden sensitive fields,
  TypeScript policy composition, diagnostics-based capability authority, and removed
  CIDR-only assumptions.
- Scope-drift check: Confirm complete M1/M2/M8/M13 product projection coverage and
  no missing approved API/UI surface. Confirm the diff adds no new network mode,
  hierarchy rule, fallback, Provider capability, persistence, lifecycle transition,
  Kubernetes evidence, traffic audit product, client-side composition, controller,
  testenv/live enforcement claim, Spec promotion, implementation date, or unrelated
  UI redesign. Confirm diagnostics remain warning-only observation and Runtime
  desired/applied slots remain the status source of truth.
- Context checkpoint: Phase 6 begins from Phase 5 commit `28f558114` with a clean
  branch and `Design delta: None`. Core parsing, canonicalization, hierarchy,
  compatibility, application impact, Provider v3 enforcement, diagnostics
  persistence/service projection, strict lifecycle, and Helm attestations are already
  implemented and validated. Product APIs still expose a legacy-only infrastructure
  union and Policy v1, Runtime status lacks bounded network fields, the Admin API has
  no diagnostics route, Admin Profile editing is Kubernetes v1/v2 CIDR-only, and the
  Workspace editor/router creates only Policy v1 CIDR restrictions. Remaining Phase
  6 work is the implementation above, generated-client regeneration, focused
  evidence, exact independent review, correction, final validation, commit/push, and
  a stacked PR against `feature/network-restriction-5-helm`. Phase 7 owns
  deterministic/live enforcement validation, Living Specs, and implementation dates;
  Phase 8 owns plan cleanup.
