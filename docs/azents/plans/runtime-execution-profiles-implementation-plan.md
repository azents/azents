---
title: "Hierarchical Runtime Execution Profiles Implementation Plan"
created: 2026-07-26
updated: 2026-07-26
tags: [runtime, provider, workspace, security, containers, backend, frontend, infra, testenv]
---

# Hierarchical Runtime Execution Profiles Implementation Plan

## Source of Truth

- Requirements: [`runtime-260726/REQ`](../requirements/runtime-260726-hierarchical-execution-profiles.md)
- ADR: [`runtime-260726/ADR`](../adr/runtime-260726-hierarchical-execution-profiles.md)
- Design: [`runtime-260726/DESIGN`](../design/runtime-260726-hierarchical-execution-profiles.md)

This document defines the reviewable stacked delivery for `runtime-260726`. It does not replace the approved Requirements, ADR, or Design, and it does not contain the per-phase execution details required before implementation begins.

## Feature Summary

The feature introduces Provider-neutral hierarchical Runtime execution Profiles. Platform policy defines the authority ceiling and named Profiles, Workspace policy narrows availability and bounds, and Agent editors choose an allowed Profile plus restrictive overrides. Execution changes are explicit Agent intent until Apply, while upper-layer restriction tightening automatically converges or safely stops affected Runtimes.

The first Kubernetes implementation uses a Provider-owned fixed privileged Docker Engine sidecar behind an unprivileged policy gateway. Runner and nested workloads never receive engine authority, host Docker access, privileged mode, Provider credentials, Kubernetes ServiceAccount credentials, or raw infrastructure customization. Kubernetes NetworkPolicy is the final egress authority. Nested-engine storage remains separate from the Agent Workspace and is ephemeral initially on `home`.

## Delivery Goal

Every PR in the stack must pass its required GitHub CI checks before it is treated as complete. The final stack must pass its complete CI matrix. Capability enablement additionally requires qualified Kubernetes isolation evidence; without that evidence, the privileged-engine modules remain unavailable and unadvertised rather than being enabled with weaker validation.

At the beginning of every phase, the primary agent rereads the active `ship-feature` Skill and reports a concise phase recap before creating the mandatory phase execution plan or editing implementation code.

## Stable Delivery Team

| Role | Assigned subagent | Persistent ownership | Planned phases |
| --- | --- | --- | --- |
| Implementation owner | `/root/runtime-execution-implementer` | All implementation workstreams under phase-specific path ownership: backend domain, API/client generation, Runtime Control, Provider/Helm, gateway/Runner, UI, and testenv | 1 through validation fixes |
| Independent reviewer | `/root/runtime-execution-reviewer` | Independent review of every implementation, validation, spec-promotion, and cleanup PR; no implementation ownership | 1 through cleanup |
| Primary orchestrator | `/root` | Stack design, plan/phase-plan authorship, branch and PR sequencing, integration, validation, accepted review fixes, CI monitoring, and phase progression | Entire stack |

The team is intentionally one persistent implementation owner and one independent reviewer. No phase-specific owner replacement is planned. A role change requires a documented incompatibility or unavailability and an update to this plan before work continues.

## Stack Shape

```text
main
  <- feature/runtime-execution-profiles-01-design-baseline
  <- feature/runtime-execution-profiles-02-implementation-plan
  <- feature/runtime-execution-profiles-03-policy-domain
  <- feature/runtime-execution-profiles-04-management-api-clients
  <- feature/runtime-execution-profiles-05-application-control
  <- feature/runtime-execution-profiles-06-kubernetes-enforcement
  <- feature/runtime-execution-profiles-07-gateway-engine
  <- feature/runtime-execution-profiles-08-product-ui
  <- feature/runtime-execution-profiles-09-validation
  <- feature/runtime-execution-profiles-10-spec-promotion
  <- feature/runtime-execution-profiles-11-cleanup
```

| PR | Branch | Base | Boundary |
| --- | --- | --- | --- |
| 1/11 | `feature/runtime-execution-profiles-01-design-baseline` | `main` | Approved Requirements, ADR, Design, and generated docs index |
| 2/11 | `feature/runtime-execution-profiles-02-implementation-plan` | 1/11 | This multi-phase delivery plan |
| 3/11 | `feature/runtime-execution-profiles-03-policy-domain` | 2/11 | Phase 1: policy domain, resolver, audit, snapshot model, and safe migration |
| 4/11 | `feature/runtime-execution-profiles-04-management-api-clients` | 3/11 | Phase 2: Admin and Public policy APIs, authorization, OpenAPI, generated clients |
| 5/11 | `feature/runtime-execution-profiles-05-application-control` | 4/11 | Phase 3: Agent Apply, convergence, target/applied snapshots, Runtime Control evidence |
| 6/11 | `feature/runtime-execution-profiles-06-kubernetes-enforcement` | 5/11 | Phase 4: Kubernetes multi-container resource model, NetworkPolicy ownership, engine storage, Helm/RBAC |
| 7/11 | `feature/runtime-execution-profiles-07-gateway-engine` | 6/11 | Phase 5: policy gateway, fixed engine, Runner Docker client contract, image/CI integration |
| 8/11 | `feature/runtime-execution-profiles-08-product-ui` | 7/11 | Phase 6: Admin, Workspace, Agent, and Runtime policy UX |
| 9/11 | `feature/runtime-execution-profiles-09-validation` | 8/11 | Phase 7: deterministic E2E/testenv validation and implementation/spec comparison |
| 10/11 | `feature/runtime-execution-profiles-10-spec-promotion` | 9/11 | Living spec promotion and implemented snapshot marking after complete verification |
| 11/11 | `feature/runtime-execution-profiles-11-cleanup` | 10/11 | Remove temporary plans and stale implementation-only references |

## Dependencies and Parallelization

The stack is sequential at the PR level because each phase exposes the next phase's durable interfaces. No later implementation branch is created until the current phase PR exists.

```mermaid
flowchart LR
    D[1 Design baseline] --> P[2 Implementation plan]
    P --> A[3 Policy domain]
    A --> B[4 APIs and clients]
    B --> C[5 Apply and Control]
    C --> K[6 Kubernetes enforcement]
    K --> G[7 Gateway and engine]
    G --> U[8 Product UI]
    U --> V[9 Validation]
    V --> S[10 Spec promotion]
    S --> X[11 Cleanup]
```

Within an implementation phase, work may run in parallel only when the mandatory phase execution plan assigns non-overlapping paths and fixed interfaces. The persistent implementation owner handles one bounded workstream at a time unless the phase plan explicitly permits independent owned-path work. The primary orchestrator owns shared integration and applies localized review fixes.

## Phase Delivery Plan

### Phase 1 — Execution-policy domain, resolver, migration

**PR:** `runtime-execution-profiles [3/11]: Phase 1 — Policy domain`

Purpose:

- Introduce the first-class mutable Platform, Profile, Workspace, and Agent execution-policy domain.
- Define the Azents-owned typed capability module catalog, canonicalization, restrictive merge, dependency validation, direction classification, and bounded reason codes.
- Extend immutable Runtime Policy Snapshots for execution-policy source trace and support repeated target/applied attachment.
- Add metadata-only execution-policy audit persistence.
- Seed reserved `system-standard`, backfill all existing Agents, and preserve baseline-equivalent active Runtime behavior.

Boundary:

- Includes backend persistence, domain services, migration, and focused tests.
- Does not expose management APIs, provide a Docker-compatible gateway, alter Kubernetes Pod topology, or grant new execution capability.

Dependencies:

- Design baseline and implementation plan only.

Validation:

- Generated additive Alembic revision plus representative upgrade verification.
- Resolver property/unit tests for boolean intersection, numeric minima, allow intersection, deny union, persistence narrowing, dependencies, unknown values, and no fallback.
- Repository/service tests for version conflicts, audit atomicity, Standard migration, and target/applied snapshot invariants.
- Backend Ruff, format, Pyright, focused and affected test suites.

### Phase 2 — Management APIs and generated clients

**PR:** `runtime-execution-profiles [4/11]: Phase 2 — Management APIs and clients`

Purpose:

- Add System Admin Platform/Profile management APIs and safe audit/compatibility projections.
- Add Workspace policy APIs with backend-enforced OWNER/MANAGER mutation and MEMBER read access.
- Add Agent Profile intent/override read/write APIs under existing Agent administration boundaries.
- Regenerate Admin/Public OpenAPI clients for Python and TypeScript.

Boundary:

- Includes API/service authorization, OpenAPI artifacts, generated clients, and API tests.
- Does not add Agent Apply, automatic convergence, protocol changes, Provider capability enablement, or UI implementation.

Dependencies:

- Phase 1 domain/service interfaces and migration.

Validation:

- Authorization matrix tests for System Admin, OWNER, MANAGER, MEMBER, and Agent admin.
- Expected-version conflict tests and safe-projection secret exclusion tests.
- OpenAPI dump/regeneration and generated-client drift checks.
- Backend and client package quality checks.

### Phase 3 — Apply, convergence, and Runtime Control evidence

**PR:** `runtime-execution-profiles [5/11]: Phase 3 — Application and Control`

Purpose:

- Add explicit Agent Apply and durable automatic convergence scheduling/scanning.
- Create target snapshots atomically with desired-generation advancement and promote applied snapshots only from exact evidence.
- Extend Runtime Control protobuf/shared contracts, backend Control validation, Provider adapters, and Runner evidence with snapshot ID, digest, module versions, and generation fields.
- Ensure incompatible or mixed-version Providers fail closed and cannot report a policy-enabled Runtime compliant.

Boundary:

- Includes backend lifecycle, scheduler/convergence, proto/shared library, Control service, Docker/Kubernetes Provider protocol adapters, Runner contract, and focused tests.
- Does not change Kubernetes Pod topology, introduce engine storage, implement gateway behavior, or expose final UI.

Dependencies:

- Phase 1 policy domain and Phase 2 API intent surfaces.

Validation:

- Proto round-trip and generated artifact checks.
- Target/applied promotion, stale/missing/mismatched evidence, desired-generation, and convergence idempotency tests.
- Explicit Apply versus expansion pending versus restriction auto-target tests.
- Quality suites for backend, runtime-control library, Runner, and both Providers.

### Phase 4 — Kubernetes enforcement resource model

**PR:** `runtime-execution-profiles [6/11]: Phase 4 — Kubernetes enforcement`

Purpose:

- Extend Kubernetes Provider resource and HTTP models for generated multi-container Pod topology, per-container security, commands, volumes, engine storage, and Runtime-specific NetworkPolicies.
- Restructure broad Runtime egress policy so Profile-managed Pods are excluded from broad public egress before restrictive Runtime policies are introduced.
- Add narrowly scoped NetworkPolicy RBAC and Helm/render regression coverage.
- Implement separate ephemeral engine storage; retain persistent mode unavailable unless Provider storage capability proves a bound.

Boundary:

- Includes Kubernetes Provider, Helm/RBAC/network policy, provider contract declaration, and tests.
- Does not add gateway request authorization or enable Engine modules in Profiles.
- Does not expose user-configurable Kubernetes fields, host Docker access, or a generic privileged toggle.

Dependencies:

- Phase 3 exact application evidence and Provider contract support.

Validation:

- Kubernetes model/serializer/parser/reuse tests.
- Helm lint/render tests for Pod topology, no hostPath/host socket/ServiceAccount token, narrowed RBAC, NetworkPolicy selector isolation, and additive-policy regression.
- Workspace PVC preservation and separate engine storage lifecycle tests.

### Phase 5 — Policy gateway, fixed engine, and Runner client

**PR:** `runtime-execution-profiles [7/11]: Phase 5 — Gateway and engine`

Purpose:

- Add the unprivileged container policy gateway and its immutable image build path.
- Add Provider-owned fixed privileged engine integration, private engine socket, gateway socket, and Runner Docker/Compose client contract.
- Enforce independently authorized build, run, and Compose operations and reject unsafe Docker API options.
- Integrate CI/release/snapshot image builds and digest/provenance expectations.

Boundary:

- Includes the new gateway application and image, Runner image tooling, Kubernetes Provider integration necessary for the fixed topology, and exhaustive gateway tests.
- Does not add rootless engine support, persistent engine enablement on `home`, raw Docker API passthrough, raw Pod customization, or user-controlled engine images.

Dependencies:

- Phase 4 generated topology, NetworkPolicy ownership, and storage contracts.

Validation:

- Gateway protocol conformance and negative request tests for privilege, host mount/device/namespace, capabilities, network bypass, resource/storage overages, unauthorized ports, Compose, and build entitlements.
- Image build and no-secret/no-socket exposure checks.
- Runtime Provider/Runner integration tests with snapshot digest evidence.

### Phase 6 — Product UI

**PR:** `runtime-execution-profiles [8/11]: Phase 6 — Product UI`

Purpose:

- Add Admin Runtime Execution management UI.
- Add Workspace Runtime Execution restriction UI.
- Add Agent Profile, restrictive override, configured/pending/applied/unavailable/divergent views, and explicit Apply UI.
- Add safe Runtime diagnostics and stories for meaningful state variants.

Boundary:

- Includes hand-written frontend code and UI tests/stories.
- Uses generated clients from Phase 2 and status/API contracts from Phase 3.
- Does not introduce new backend policy semantics or expose implementation-sensitive Provider details.

Dependencies:

- Phase 2 APIs/clients, Phase 3 application projections, and Phase 5 capability behavior.

Validation:

- TypeScript format, lint, typecheck, build, focused component/container tests, and Storybook coverage where supported.
- Role and state presentation tests; backend remains the authority for permissions and status.

### Phase 7 — E2E/testenv validation

**PR:** `runtime-execution-profiles [9/11]: Phase 7 — Validation`

Purpose:

- Run deterministic API and Runtime behavior validation.
- Add or complete testenv prerequisites and fixture support through Admin/Public APIs rather than direct product-state DB seeding.
- Record commands, environment metadata, evidence, failures, fixes, and strict current-spec comparison.

Boundary:

- Includes validation report, testenv/E2E fixtures, and defects discovered by validation.
- Does not mark Requirements/Design implemented or remove plans.

Dependencies:

- Phases 1 through 6.

Validation:

- Full required CI matrix and planned deterministic E2E scenarios.
- Qualified Kubernetes evidence for privileged-engine topology, CNI NetworkPolicy enforcement, and storage lifecycle when the capability is advertised.
- If qualified evidence is absent, verify the capability remains unavailable/unadvertised and record that state; do not convert absent live evidence into a successful enablement claim.

### Phase 8 — Spec promotion

**PR:** `runtime-execution-profiles [10/11]: Spec promotion`

Purpose:

- Run `/spec-review` against the completed implementation.
- Update affected living Runtime Provider, Agent, Workspace, persistence, and Runtime Control specs.
- Mark Requirements and Design implemented on the same verified date only after all validation and CI evidence are complete.

Boundary:

- Documentation/spec changes and any narrowly required documentation correction only.
- Does not change product behavior or rewrite accepted ADR decisions.

Dependencies:

- Phase 7 validation evidence and passing stack CI.

### Phase 9 — Cleanup

**PR:** `runtime-execution-profiles [11/11]: Cleanup`

Purpose:

- Remove this multi-phase plan and all phase execution plans after implementation and spec promotion are complete.
- Remove stale implementation-only references while retaining immutable Requirements, ADR, Design, and current living specs.

Boundary:

- Cleanup-only; no behavior changes or refactors.

Dependencies:

- Phase 8 spec promotion.

## Data, API, Runtime, and UI Change Map

| Area | Phase ownership | Principal change |
| --- | --- | --- |
| Policy persistence and migration | Phase 1 | Current-state policy rows, Standard seed/backfill, audit, target/applied snapshot pointers |
| Policy resolver | Phase 1 | Typed Azents-owned catalog, monotone merge, compatibility and direction classification |
| Admin/Public API and generated clients | Phase 2 | Platform/Profile, Workspace, Agent intent, audit, effective projections |
| Apply/convergence and Control | Phase 3 | Explicit Apply, idempotent restriction convergence, typed policy evidence and generation validation |
| Kubernetes Provider/Helm | Phase 4 | Multi-container resource model, NetworkPolicy resources/RBAC, engine storage, broad-policy isolation |
| Gateway/engine/Runner | Phase 5 | Docker-compatible mediation, fixed engine, private socket boundary, image CI integration |
| Frontend | Phase 6 | Admin, Workspace, Agent, Runtime policy UX using generated clients |
| Testenv/E2E | Phase 7 | API-managed fixtures, deterministic Runtime checks, qualified Kubernetes evidence |
| Living specs | Phase 8 | Current behavior promotion |

## E2E Primary Validation Matrix

| Behavior | Required outcome | Primary evidence | Earliest phase |
| --- | --- | --- | --- |
| Existing Agent migration | Every Agent selects `system-standard`; no new capability or baseline Runtime replacement | migration/API state and Runtime generation evidence | 1, validated 7 |
| Restrictive hierarchy | Lower layers cannot restore Platform/Workspace denial | resolver/property and API conflict tests | 1–2 |
| Explicit Apply | Agent save is pending and grants no authority until Apply | API/Runtime target-applied evidence | 3 |
| Automatic tightening | Restriction creates compliant target or safely stops unsatisfiable Runtime | desired generation, snapshot, state, Workspace preservation | 3, validated 7 |
| Provider incompatibility | No weaker provisioning or readiness | compatibility projection and failed lifecycle evidence | 3 |
| Build-only Profile | Build is allowed; run and Compose are gateway-denied | gateway contract and Runtime integration | 5, validated 7 |
| Run/Compose controls | Unsafe Docker fields and disabled operations are denied | gateway negative tests | 5, validated 7 |
| Nested egress | Nested workloads cannot bypass direct, no-network, or proxy-required policy | Pod/NetworkPolicy evidence and allowed/denied endpoints | 4–5, validated 7 |
| Engine storage | Ephemeral state disappears on replacement; Workspace remains; persistent remains unavailable on `home` | PVC/volume identity and cache checks | 4, validated 7 |
| Safe UI | Roles and configured/pending/applied/unavailable/divergent state render from server projections | UI tests/stories and E2E | 6–7 |

## Fixture and Prerequisite Requirements

### Deterministic CI fixtures

- Compatible and incompatible Provider capability-contract fixtures.
- Platform Profile, Workspace policy, and Agent intent setup through Admin/Public APIs.
- Runtime snapshot and desired-generation inspection helpers.
- Gateway allow/deny fixtures and a secret-safe operation record.
- Allowed and denied network test endpoints.
- Workspace checksum and engine-state probe helpers.
- Kubernetes manifests and NetworkPolicy evidence collection without projected token, credentials, or secret data.

### Qualified Kubernetes validation prerequisite

Privileged-engine enablement requires a qualified Kubernetes environment that can prove:

- admission accepts exactly the Provider-owned fixed topology;
- CNI enforces the generated NetworkPolicies for nested traffic;
- no host socket, host path, ServiceAccount token, Provider credential, or Runtime Control credential leaks into Runner, gateway, engine, or nested workload paths;
- engine and Workspace storage lifecycle is correct;
- image digests and Provider contract evidence match the test record.

The current CI does not provide this environment. This blocks Phase 7 enablement evidence, not fail-closed code delivery. Until it exists, the Kubernetes Provider must not advertise or enable the privileged-engine execution modules.

Persistent engine storage also requires a Provider-qualified storage backend with enforceable capacity. The current `home` local-path configuration remains ephemeral-only.

## Test Strategy by Phase

| Phase | Required checks |
| --- | --- |
| 1 | Alembic upgrade/invariants; backend Ruff/format/Pyright/pytest; resolver and migration tests |
| 2 | backend API/auth tests; OpenAPI dump; generated Python/TypeScript client checks; drift checks |
| 3 | proto generation/round-trip; backend/control/Runner/Docker+Kubernetes Provider quality and focused tests |
| 4 | Kubernetes Provider quality/tests; Helm lint/render tests; NetworkPolicy/RBAC and PVC lifecycle regression tests |
| 5 | gateway quality/tests; Runner/Provider integration; image build and socket/secret boundary tests |
| 6 | TypeScript format/lint/typecheck/build; component/container/story tests |
| 7 | full affected CI matrix, deterministic E2E, qualified prerequisite validation, evidence report |
| 8 | `/spec-review`, docs snapshot/index checks |
| 9 | docs/index checks and final static scan |

Every phase also requires:

- `git diff --check`;
- a scope-drift review against its phase execution plan;
- primary-agent verification;
- independent review by `/root/runtime-execution-reviewer` after verification;
- review-finding remediation and recheck when findings are accepted;
- a PR created before any later phase branch begins.

## Known Risks and Blockers

| Item | Status | Blocked phase or behavior | Required handling |
| --- | --- | --- | --- |
| Target/applied snapshot lifecycle is currently creation-only | Known implementation gap | Phase 1 and 3 | Add explicit pointers and mutation paths; do not overload the existing create-only attachment rule |
| Existing broad egress NetworkPolicy is additive | Known implementation gap | Phase 4 | Exclude Profile-managed Pods before generated restrictive policies exist; test against accidental outage and bypass |
| Provider has no NetworkPolicy RBAC | Known implementation gap | Phase 4 | Add only workload-namespace NetworkPolicy permissions; preserve no Secret/TokenReview authority |
| Gateway and engine image do not exist | Known implementation gap | Phase 5 | Build fixed Provider-owned artifacts and CI integration; no user image override |
| Qualified privileged K8s/CNI/storage evidence absent | External prerequisite | Phase 7 capability enablement | Keep modules unavailable/unadvertised until evidence passes |
| `home` persistent capacity is not proven | Environment limitation | Persistent storage behavior | Advertise ephemeral only; do not treat PVC request as hard quota |
| Gateway Docker/Compose compatibility | High implementation risk | Phase 5 and 7 | Use a closed endpoint/field contract and exhaustive negative/conformance tests |
| Generated API clients | Required process | Phase 2 and 3 API changes | Regenerate from OpenAPI; never hand-edit |

## Spec Impact Candidates

Implementation is expected to update:

- `docs/azents/spec/domain/runtime-provider.md`;
- `docs/azents/spec/domain/agent.md`;
- `docs/azents/spec/domain/workspace.md`;
- `docs/azents/spec/flow/agent-runtime-persistence.md`;
- `docs/azents/spec/flow/agent-runtime-control.md`;
- a new execution-policy domain living spec if the expanded Runtime Provider spec would no longer remain legible.

Spec promotion occurs only in PR 10/11 after validation. Earlier phases update a living spec only when a new current behavior cannot remain undocumented safely until that PR.

## Rollout and Cleanup Notes

- The Platform policy initially exposes only `system-standard` and no privileged-engine capability.
- Existing Agents migrate to `system-standard` without forced baseline-equivalent Runtime replacement.
- Provider support is fail closed through accepted contracts, target/applied evidence, and profile compatibility.
- `home` initially advertises ephemeral engine storage only.
- Disabling an enabled authority-bearing Profile converges Runtimes safely or stops unsatisfiable Runtimes without Profile fallback, reset, terminal deletion, Workspace loss, or persistent engine PVC loss outside the defined lifecycle.
- The stack must be merged front-to-back. Rebase/retarget operations use the `stacked-prs` workflow and `--force-with-lease` only when necessary.
- PR 11 removes this plan and all phase execution plans once living specs are current and the snapshot is marked implemented.
