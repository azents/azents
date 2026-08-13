---
title: "Hierarchical Runtime Network Restriction Implementation Plan"
created: 2026-08-12
tags: [runtime, network, security, provider, kubernetes, frontend, testenv]
---

# Hierarchical Runtime Network Restriction Implementation Plan

- Requirements: [`network-260812/REQ`](../requirements/network-260812-hierarchical-runtime-network-restriction.md)
- Decisions: [`network-260812/ADR`](../adr/network-260812-hierarchical-runtime-network-restriction.md)
- Approved Design: [`network-260812/DESIGN`](../design/network-260812-hierarchical-runtime-network-restriction.md)
- Approved Design revision: `2`
- Approved mechanism IDs: `M1` through `M15`
- Design delta: `None`
- Implementation owner: Primary agent (`/root`)
- Independent reviewer: `network-260812-reviewer` (`/root/network-260812-reviewer`)

## Delivery Shape

The feature ships as eight stacked PRs. Each implementation phase is reviewed and
passes its focused validation before its PR is opened. Every planned PR is opened
before stack-wide CI monitoring begins.

| Phase | Branch | Base | PR title | Approved mechanisms | Primary boundary |
| --- | --- | --- | --- | --- | --- |
| 1 | `feature/network-restriction-1-contracts` | `origin/main` | `Runtime network restriction [1/8]: Add hierarchical profile contracts` | `M1`, `M2`, `M11` | Kubernetes Profile v3, Workspace Policy v2, canonical domain/CIDR hierarchy, mode-aware capabilities and impact classification |
| 2 | `feature/network-restriction-2-control` | Phase 1 | `Runtime network restriction [2/8]: Add protocol v3 enforcement evidence` | `M8`, `M9`, `M10` | Runtime Control protocol v3, aggregate evidence admission and repair fencing, connection-generation diagnostics migration |
| 3 | `feature/network-restriction-3-provider-resources` | Phase 2 | `Runtime network restriction [3/8]: Add strict network resource primitives` | `M4`, `M5`, `M6`, `M7`, `M14` | Typed Kubernetes Service/ConfigMap/Secret/Pod inputs, CA and policy artifacts, proxy addon/image, Runner trust bootstrap |
| 4 | `feature/network-restriction-4-provider-lifecycle` | Phase 3 | `Runtime network restriction [4/8]: Enforce strict network lifecycle` | `M3`, `M7`, `M10`, `M11`, `M12` | Provider resource lifecycle, complete policies, aggregate reconciliation, recovery, narrow-first transitions, v2 actionable removal |
| 5 | `feature/network-restriction-5-helm` | Phase 4 | `Runtime network restriction [5/8]: Package strict network enforcement` | `M3`, `M4`, `M6`, `M7`, `M8` | Default-disabled attestations, immutable artifacts, mandatory Service references, narrow RBAC, chart render coverage |
| 6 | `feature/network-restriction-6-product` | Phase 5 | `Runtime network restriction [6/8]: Expose network policy controls` | `M1`, `M2`, `M8`, `M13` | Admin/Public API projections, OpenAPI and generated clients, Admin and Workspace profile/status web surfaces |
| 7 | `feature/network-restriction-7-validation` | Phase 6 | `Runtime network restriction [7/8]: Validate and document enforcement` | `M15` plus full `M1`-`M15` validation | deterministic API/control-plane E2E, Kubernetes Provider/proxy tests, Living Specs, implementation dates, delivery evidence |
| 8 | `feature/network-restriction-8-cleanup` | Phase 7 | `Runtime network restriction [8/8]: Remove implementation plans` | full approved delivery cleanup | remove temporary overall and phase plans after validation and Spec promotion |

## Fixed Interfaces and Integration Boundaries

- Infrastructure Profile v1/v2 and Workspace Policy v1 remain readable and retain
  their direct-network meaning. The initial delivery does not rewrite stored legacy
  documents or applied configuration.
- Profile v3 contains one discriminated `network_access` mode. Policy v2 contains one
  discriminated restrictive `network_restriction`. The server is the only hierarchy
  composition authority.
- Canonical domain patterns are lowercase IDNA ASCII exact hosts or leading-label
  wildcards. Empty allowlists never infer a mode.
- The existing desired/applied configuration sequence, digest, desired generation,
  Provider acknowledgement, and Runner acknowledgement remain product truth.
- Kubernetes protocol v3 admits one aggregate actionable `network_enforcement`
  observation. Runtime Control never persists or interprets individual Kubernetes
  resource inventory.
- Kubernetes Provider owns Runtime Pod, Workspace PVC, Runtime NetworkPolicy, logical
  Runtime CA Secret, proxy policy ConfigMap, stable proxy Service, proxy Pod, and proxy
  ingress/egress NetworkPolicies.
- Strict Runtime Pods have no DNS egress. Provider-observed mandatory Service addresses
  are injected as exact host aliases; there is no DNS component or fallback.
- Proxy environment and trust variables are compatibility inputs. Complete
  NetworkPolicies plus operator-owned enforcing CNI are the anti-bypass authority.
- Strict capabilities are independently enabled by default-disabled operator
  attestations. Deployment validation is warning-only and does not become capability
  or enforcement authority.
- CIDR-only changes are in place. Proxy policy or artifact changes replace only proxy
  resources. Mode, CA trust, Runtime DNS, or mandatory hosts changes require Runtime
  recreation. Authority is narrowed before replacement.
- Workspace PVC deletion remains limited to existing reset and terminal-delete
  boundaries. Stop and ordinary replacement preserve it.
- API/control-plane E2E is distinct from Kubernetes Provider/proxy unit, manifest,
  protocol, lifecycle, trust, and forwarding validation. Neither test layer becomes
  capability authority or claims live packet enforcement.

## Phase Dependencies and Context Checkpoints

### Phase 1 — Contracts and composition

Historical Phase 1 inputs: then-approved Design revision 1 and the pre-feature Profile v1/v2 and
Policy v1 behavior. The current delivery and review authority is approved Design revision 2.

Outputs:

- typed Kubernetes Profile v3 network modes and Policy v2 restriction variants;
- canonical CIDR and domain normalization, hierarchy, inherited denial, and expansion
  rejection;
- legacy-to-v3 effective composition for Policy v2 without legacy data rewrites;
- mode-aware Provider capability compatibility;
- mode/input-aware application impact classification; and
- focused parsing, composition, compatibility, digest, and impact tests.

Checkpoint to Phase 2: Runtime Control and the Kubernetes Provider can consume the
canonical v3 effective Profile shape, while protocol and Kubernetes behavior remain
unchanged.

### Phase 2 — Runtime Control v3 and diagnostics persistence

Inputs: canonical effective Profile v3 and mode-aware impact result.

Outputs:

- protocol-v3 registration and operational diagnostics payload;
- aggregate `network_enforcement` report model, admission, applied promotion, stale
  rejection, and current-observe repair fencing;
- fail-closed rejection of incompatible Provider protocol/config versions;
- generated protobuf artifacts;
- generated linear expand migration for nullable connection diagnostics JSONB and
  checked-at fields, repository/service generation fencing, and Admin-safe data model;
  and
- focused protocol, migration, persistence, reconciliation, and redaction tests.

Checkpoint to Phase 3: v3 Control contracts are available, but strict capability
attestations remain disabled and no strict Runtime can yet be applied.

### Phase 3 — Provider resource primitives, CA, proxy, and trust

Inputs: Profile v3 and protocol-v3 types.

Outputs:

- typed Kubernetes API/HTTP support for Services, ConfigMaps, Secrets, selected Secret
  and ConfigMap volumes, host aliases, and strict DNS configuration;
- deterministic owned resource naming, labels, annotations, parsers, and comparison
  views;
- persistent logical-Runtime CA generation and validation with public/private
  separation;
- canonical proxy policy document and digest;
- pinned mitmdump plus Azents addon image implementation and conformance tests;
- Runner public-CA validation, inherited trust-bundle preparation, and child-process
  trust variables; and
- focused Kubernetes transport, crypto, addon, redaction, and Runner tests.

Checkpoint to Phase 4: all strict resource primitives exist, but Provider lifecycle
does not yet activate the complete enforcement bundle.

### Phase 4 — Provider lifecycle and enforcement

Inputs: strict resource primitives and protocol-v3 aggregate evidence.

Outputs:

- complete direct, proxy-only, Platform-only, and proxy ingress/egress policies;
- mandatory Service observation and strict Runtime hosts/DNS inputs;
- proxy preparation/readiness before Runtime creation;
- mode-aware create, observe, in-place update, restart, stop, reset, recovery, and
  terminal deletion;
- persistent CA and stable Service retention plus existing PVC semantics;
- narrow-first transitions and recreation-required outcomes;
- aggregate `network_enforcement` evidence; and
- removal of any v2 `network_policy` fallback for v3 strict contracts while retaining
  the legacy direct v2 path.

Checkpoint to Phase 5: the Provider can enforce and prove strict modes when configured,
but chart attestations remain default-disabled until packaged.

### Phase 5 — Helm packaging and operator attestations

Inputs: Provider strict lifecycle and its exact deployment settings.

Outputs:

- independent default-disabled `proxyRequired` and `noNetwork` attestations;
- immutable proxy/addon artifact configuration and validation;
- explicit mandatory Platform Service references;
- workload-resource Role changes and resource-name-scoped mandatory Service reads;
- default-deny and dedicated namespace documentation;
- warning-only startup diagnostic settings; and
- schema and render tests proving disabled defaults, exact RBAC, and absence of a new
  DNS/proxy controller Deployment.

Checkpoint to Phase 6: operators can deploy the strict Provider boundary explicitly,
while product APIs and UI still require the new projections.

### Phase 6 — Product APIs and web surfaces

Inputs: final server/Profile/Provider contracts and packaged capability settings.

Outputs:

- Admin infrastructure Profile v1/v2/v3 and Workspace Policy v1/v2 API unions;
- safe effective network and desired/applied Runtime projections;
- active connection diagnostics and disconnected-unavailable Admin projection;
- bounded failure and compatibility codes;
- regenerated Admin/Public OpenAPI and Python/TypeScript clients;
- Admin Profile and Provider diagnostic surfaces;
- Workspace Profile and Runtime status surfaces with localized compatibility guidance;
  and
- component, story, router, API, and generated-contract tests.

Checkpoint to Phase 7: all approved product behavior is implemented and exposed, with
no TypeScript-side policy composition.

### Phase 7 — Validation, Specs, and implementation record

Inputs: stable complete implementation and the credential-free E2E fixture.

Outputs:

- deterministic contract, Provider, Runner, addon, Helm, generated-client, and
  control-plane E2E coverage;
- explicit separation between API/control-plane evidence and Kubernetes
  Provider/proxy unit, manifest, protocol, lifecycle, trust, and forwarding evidence;
- full authority, removal, security, lifecycle, migration, rollout, and rollback audit;
- updated Runtime Provider, Runtime Control, Workspace, persistence, and E2E Living
  Specs;
- matching `implemented: 2026-08-13` dates on Requirements and Design only after
  required implementation validation succeeds; and
- recorded validation commands, environments, failures, corrections, and explicit
  non-packet evidence classification.

Checkpoint to Phase 8: implementation and Specs are authoritative and verified; only
temporary implementation plans remain.

### Phase 8 — Plan cleanup

Inputs: Phase 7 implementation dates, promoted Specs, and stable validation evidence.

Outputs:

- deletion of this plan and all eight phase execution plans;
- documentation/index validation; and
- final absence proof that no feature implementation plan remains.

Checkpoint: the complete PR stack exists and required GitHub checks pass. PRs remain
unmerged until separate requester approval.

## Workstream Ownership

| Workstream | Owner | Primary paths | Interfaces produced or consumed |
| --- | --- | --- | --- |
| Profile and Workspace policy contracts | `/root` | `python/apps/azents/src/azents/core/runtime_profile.py`, Profile services and focused tests | v3/v2 models, canonical composition, capability and impact results |
| Runtime Control and persistence | `/root` | `proto/azents/runtime_control/v1/**`, `python/libs/azents-runtime-control/**`, Runtime Control services/repositories/models/migrations | protocol v3, aggregate evidence, diagnostics snapshot |
| Kubernetes Provider and proxy | `/root` | `python/apps/azents-runtime-provider-kubernetes/**`, proxy image/addon paths | typed resources, CA, policies, lifecycle, aggregate reports |
| Runtime Runner | `/root` | `python/apps/azents-runtime-runner/**` | public trust bootstrap and inherited child-process environment |
| Helm packaging | `/root` | `infra/charts/azents/**` | attestations, artifacts, mandatory Services, RBAC |
| API and generated contracts | `/root` | Backend Admin/Public routes/models/specs and generated Python/TypeScript clients | bounded projections and source-generated clients |
| Web products | `/root` | `typescript/apps/azents-admin-web/**`, `typescript/apps/azents-web/**` | mode-aware forms, diagnostics, effective status, localized guidance |
| Validation and Specs | `/root` | `testenv/azents/**`, `docs/azents/spec/**`, snapshot frontmatter | deterministic/live evidence and living behavior |
| Independent review | `/root/network-260812-reviewer` | read-only across every phase diff | authority, security, lifecycle, migration, interface, and scope report |

The reviewer never modifies files. A phase plan narrows exact owned paths before each
implementation phase begins.

## Removal Obligations

| Removal | Owning phase | Replacement | Absence verification |
| --- | --- | --- | --- |
| v1/v2 `network_policy` as the only new Kubernetes contract shape | 1 | Profile v3 `network_access`; legacy parsers retained | parser/API tests require v3 for strict contracts while v1/v2 fixtures remain unchanged |
| Policy v1 as the only editable Workspace policy | 1 and 6 | Policy v2 hierarchy; Policy v1 retained direct-only | server and generated/UI tests cover both versions |
| `network_policy` as the only Kubernetes reconciliation contract | 4 | protocol-v3 aggregate `network_enforcement` for v3 strict contracts while protocol v2 remains legacy direct-only | protocol/Control tests separate v2 compatibility from v3 strict evidence and reject cross-version fallback |
| Provider API limited to Pod/PVC/NetworkPolicy | 3 | typed Service/ConfigMap/Secret/hosts/DNS boundary | typed transport tests and exact method search |
| Runner without interception trust bootstrap | 3 | validated public-CA appended trust bundle | Runner tests and mounted-key absence assertions |
| Runtime DNS in strict modes | 4 | strict DNS configuration plus mandatory host aliases | exact manifest and comparison tests |
| direct customer egress in proxy/no-network modes | 4 | proxy-only or Platform-only complete Runtime policy | exact policy equality and negative-rule assertions |
| NetworkPolicy-only in-place Provider update | 4 | mode-aware bounded enforcement-bundle update | lifecycle and recreation-required tests |
| Provider workload RBAC limited to Pod/PVC/NetworkPolicy | 5 | narrow owned-resource CRUD plus named Service reads | Helm render assertions for resources, names, namespaces, and verbs |
| CIDR-only Admin and Workspace editors | 6 | mode-aware CIDR/domain forms and explanations | stories, component tests, and Web Surface E2E |
| Runtime status without effective network mode | 6 | bounded desired/applied network projection | API/UI tests and sensitive-field absence checks |
| connection projection without warning diagnostics | 2 and 6 | generation-scoped snapshot and disconnected-unavailable projection | migration, generation-fence, redaction, disconnect, and Admin tests |
| strict-mode validation limited to API composition | 7 | Provider/proxy unit, manifest, protocol, lifecycle, trust, and forwarding tests alongside control-plane E2E | focused deterministic suites and explicit non-packet labeling |
| temporary implementation plans | 8 | implemented snapshot, Living Specs, code, and test evidence | final tree search finds no network-260812 plan |

The existing MCP egress proxy and Workspace PVC lifecycle remain unchanged except for
coordination required by the approved strict Runtime resource lifecycle.

## Validation Matrix

- Phase-focused Python: Ruff, formatter check, configured `ty`, and targeted pytest in
  each affected subproject.
- Protobuf: source generation, generated artifact consistency, library tests, Provider
  client tests, and Control admission/reconciliation tests.
- Migration: Alembic-generated linear revision, current-head alignment, upgrade and
  downgrade tests, nullable legacy-row behavior, and `db-schemas/rdb/revision`.
- Provider: typed manifest equality, exact ownership fencing, CA/public-private
  separation, lifecycle and recovery matrix, aggregate evidence, and addon conformance.
- Runner: trust bootstrap, failure behavior, inherited environment, and direct/no-network
  absence.
- Helm: schema validation and render tests for default-disabled attestations, immutable
  images, mandatory Services, exact RBAC, default deny, and no extra controller.
- Generated contracts: OpenAPI dump and source generation for Admin/Public Python and
  TypeScript clients; generated files are never manually edited.
- TypeScript: formatting, lint, typecheck, targeted unit/component/story tests, and
  affected app builds.
- E2E: credential-free deterministic Admin/Public API and Runtime Control journey in
  required CI, explicitly limited to control-plane behavior.
- Documentation: snapshot validator, generated index hook, `/spec-review`, authority
  and removal audit, frontmatter validation, and `git diff --check`.
- Final stack: all planned PRs exist before required GitHub check monitoring. Failures
  are corrected in the owning phase and dependent branches are rebased.

## Prerequisites and Blockers

- Deterministic implementation and control-plane E2E require no live credential.
- Migration integration requires PostgreSQL and the repository migration environment.
- Provider and Runner image tests require the existing build/test substrate.
- Strict-network validation requires no Kubernetes cluster, Kubernetes credential,
  packet-probe destination, or qualification artifact.
- No live Kubernetes resource is applied, restarted, deleted, or otherwise mutated by
  this delivery task.
- Any new material behavior, persistent authority, fallback, compatibility path,
  configuration mode, resource owner, or failure contract returns to feature design.
  Local details within approved contracts retain `Design delta: None`.

## Review and Stack Policy

The exact independent reviewer for every phase is
`/root/network-260812-reviewer`. Review inputs are the confirmed Requirements, accepted
ADR, approved Design revision 2 and authority IDs `M1`-`M15`, current Specs, the phase
execution plan, focused evidence, and the stable phase diff.

Review priority is Requirements and Design authority, security and private-key
exposure, fail-closed networking, lifecycle and PVC safety, migration correctness,
desired/applied evidence, generated interfaces, compatibility boundaries, removal
obligations, and scope drift.

Each phase is committed and opened as a PR before the next phase starts. The complete
stack is opened before CI monitoring. Earlier-phase corrections use the repository
stacked-PR workflow and rebase dependent branches. PRs are never merged without
explicit requester approval.
