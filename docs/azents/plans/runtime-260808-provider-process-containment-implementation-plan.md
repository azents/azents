---
title: "Provider-Owned Runtime Process Containment Implementation Plan"
created: 2026-08-08
updated: 2026-08-08
tags: [runtime, provider, runner, security, sandbox, implementation, validation]
---

# Provider-Owned Runtime Process Containment Implementation Plan

## Approved baseline

- Requirements: [runtime-260808/REQ](../requirements/runtime-260808-provider-process-containment.md)
- ADR: [runtime-260808/ADR](../adr/runtime-260808-provider-process-containment.md)
- Design: [runtime-260808/DESIGN](../design/runtime-260808-provider-process-containment.md)
- Approved Design revision: `2`
- Approved Design Authority: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`,
  `M8`, `M9`, `M10`, `M11`, `M12`, `M13`
- Design delta: `None`

The snapshot is confirmed, all eleven material ADR decisions are accepted, Design
revision 2 is approved for the exact authority set above, and the authority and
feasibility audits found no Design blocker.

## Delivery shape

The feature uses a seven-PR stack because it changes a versioned Profile contract,
the Runner execution authority, native operation kernels, two independent Runtime
Providers, Worker readiness and prompt behavior, generated API clients, Web
presentation, deterministic E2E fixtures, and current Specs.

Stack title prefix: `runtime containment [n/7]`

| Order | Branch | Base | PR boundary |
| --- | --- | --- | --- |
| 1 | `azents/runtime-containment-1-contracts` | `main` | Approved snapshot, implementation plans, Profile v2 portable containment contract |
| 2 | `azents/runtime-containment-2-runner-backend` | phase 1 | Runner backend interface, initial bwrap adapter, pre-registration qualification, process/environment routing |
| 3 | `azents/runtime-containment-3-contained-operations` | phase 2 | Contained file, patch, Git, import, presentation, and transfer path authority |
| 4 | `azents/runtime-containment-4-docker-provider` | phase 3 | Docker Provider preparation, capability activation, temporary storage, security, real-provider E2E |
| 5 | `azents/runtime-containment-5-kubernetes-provider` | phase 4 | Kubernetes Provider preparation, capability activation, temporary storage, security, cluster E2E |
| 6 | `azents/runtime-containment-6-worker-surfaces` | phase 5 | Desired-Profile prompt, shared readiness resolver, derived API/UI projections |
| 7 | `azents/runtime-containment-7-validation-specs` | phase 6 | Full validation, E2E evidence, living Specs, implemented snapshot promotion, plan cleanup |

Each phase branch contains its mandatory phase execution plan before implementation.
Each phase PR is opened before the next phase begins. All seven PRs are created
before CI monitoring starts. CI corrections preserve stack order and rebase
dependent branches when an earlier phase changes.

## Ownership and review

| Role | Exact owner | Responsibility |
| --- | --- | --- |
| Primary implementation and orchestration | `/root` | Plans, code, tests, integration, branch stack, local validation, PR creation, CI correction |
| Independent reviewer | `/root/runtime-containment-reviewer` | Read-only Requirements, security, interface, removal, regression, and scope-drift review for every phase PR |
| GitHub reviewer | `hardtack` | Requested on every PR |

No implementation subagents are assigned. The primary owner keeps phase ownership
non-overlapping through the stack and requests the same
`/root/runtime-containment-reviewer` subagent for every independent phase review.
`hardtack` remains the GitHub reviewer requested on every PR and is not the
independent implementation reviewer.

## Fixed interfaces and boundaries

- Profile v1 remains valid and unchanged.
- Profile v2 adds the portable containment module and rejects DinD combination.
- Provider capability advertisement is not physical qualification.
- The selected backend is trusted deployment configuration, not Profile input.
- Contained Runner qualification completes before normal Control connection.
- Existing `RuntimeConfigurationEvidence`, desired/applied revision, and Runner
  generation fencing remain authoritative.
- Existing Agent-facing Runner operation envelopes and result contracts remain
  stable unless a bounded contained-execution field is strictly required.
- Agent-selected process, file, Git, import, presentation, and transfer path access
  uses one contained authority.
- Existing absolute Agent Workspace paths remain unchanged.
- Model prompt uses the desired Profile without Runner readiness input.
- Explicit Runtime operations use bounded matching-Runtime readiness.
- No containment-specific persisted lifecycle or boolean is added.
- Existing v1 Runtimes do not gain containment automatically.
- No direct-execution or weaker-backend fallback is added.

## Phase 1 — Profile contract and approved baseline

Approved mechanisms: `M1`, `M10`, `M11`.

Deliver:

- Requirements, ADR, approved Design, this implementation plan, and the phase plan.
- Version 2 Kubernetes Pod and Docker Container Profile support.
- One shared portable containment module with no backend arguments.
- DinD mutual-exclusion validation.
- Capability derivation and compatibility evaluation.
- Canonical configuration and recreation classification coverage.
- API/OpenAPI/generated-client updates required by the versioned Profile contract.
- No Provider capability advertisement and no physical Runtime behavior.

Removal obligation:

- Replace Profile-v1-only parsing/compatibility assumptions while retaining v1.

Validation:

- focused Runtime Profile unit/repository/service/API tests;
- OpenAPI and generated-client drift checks when affected;
- Python Ruff, formatting, type checking, and focused pytest;
- TypeScript generated-client type checks when affected;
- snapshot validation and `git diff --check`.

## Phase 2 — Runner backend, qualification, process, and environment

Approved mechanisms: `M3`, `M4`, `M6`, `M13`.

Deliver:

- backend-neutral contained-execution interface and backend registry;
- direct uncontained execution implementation for retained v1 behavior;
- initial bwrap adapter isolated from Runner operation handlers;
- trusted containment bootstrap parsing;
- deterministic pre-registration qualification and stable failure categories;
- code-owned Agent environment builder with reserved Runner names;
- shell and managed-process routing through the execution interface;
- descendant cancellation, timeout, Session termination, and shutdown behavior;
- Runner image package changes and focused conformance tests.

Removal obligations:

- direct Agent `create_subprocess_shell()` authority;
- Agent environment construction through `os.environ.copy()`;
- backend-specific command construction in process operation handlers.

Validation:

- Runner Ruff, format, type checking, pytest, process tests, qualification tests,
  environment canaries, and Runner image build/probe.

## Phase 3 — Contained native operations

Approved mechanisms: `M5`, `M7`, `M3`.

Deliver:

- bundled contained-operation helper and typed pipe protocol;
- file, text, search, edit, patch, move, delete, and bulk operations inside
  containment;
- Git refs, worktree, discovery, removal, and branch operations inside
  containment;
- import, presentation, image read, publication, and provider-delivery path access
  through contained helpers;
- Agent Workspace/system/tmp/process positive projection;
- binary streaming, cancellation, bounds, patch atomicity, and exact-generation
  semantics;
- existing Git credential helper retained inside the Agent environment.

Removal obligations:

- trusted Runner native file/edit/patch/search path authority;
- trusted Runner Git subprocess authority;
- trusted Runner transfer opening of Agent-selected paths;
- Runner filesystem/temporary visibility as the Agent authority.

Validation:

- Runner file/Git/transfer unit and integration suites;
- shell/native allowed-and-denied path parity;
- Workspace and `/tmp/agent` compatibility;
- Runner-private file/process/socket canaries;
- backend conformance and image validation.

## Phase 4 — Docker Provider integration

Approved mechanisms: `M2`, `M5`, `M11`, `M12`, `M13`.

Deliver:

- Docker Profile v2 capability advertisement only for contained-capable
  deployment configuration;
- Runner containment bootstrap and backend selection;
- separate Runtime Workspace, Agent temporary, and Runner-private storage;
- explicit capability-drop, no-new-privileges, security profile, and related
  Docker create/inspect fields;
- bounded pre-registration termination diagnosis;
- contained Profile recreation and rollback behavior;
- real Docker Provider product E2E and backend conformance.

Removal obligations:

- current Docker `/tmp/agent` projection that does not separate Agent and Runner
  temporary authority;
- implicit Docker container security defaults for contained Profiles.

Validation:

- Docker Provider Ruff, format, type checking, pytest;
- Docker API adapter contract tests;
- Runner image and real-provider E2E;
- Profile adoption, qualification failure, Workspace preservation, outbound
  connectivity, and rollback journeys.

## Phase 5 — Kubernetes Provider integration

Approved mechanisms: `M2`, `M5`, `M11`, `M12`, `M13`.

Deliver:

- Kubernetes Profile v2 capability advertisement only for compatible deployment
  configuration;
- Runner containment bootstrap and backend selection;
- contained Profile Agent temporary `EmptyDir` at a Runner-private backing path;
- compatible pod/container security configuration and no service-account token;
- bounded pre-registration container termination diagnosis;
- explicit incompatible RuntimeClass/security-policy failure;
- disposable real-cluster Runtime fixture and Kubernetes containment E2E.

Removal obligations:

- DinD-only shared temporary volume behavior as the only Kubernetes separate tmp
  path;
- contained Runner dependence on incompatible/default security settings.

Validation:

- Kubernetes Provider Ruff, format, type checking, pytest;
- resource rendering and Helm checks;
- disposable-cluster backend conformance and product E2E;
- PVC preservation, EmptyDir loss, NetworkPolicy-bounded egress, qualification
  failure, and rollback journeys.

## Phase 6 — Worker prompt, readiness, status, API, and Web surfaces

Approved mechanisms: `M8`, `M9`, `M10`.

Deliver:

- immediate desired-Profile behavior repository projection;
- code-owned Runtime behavior prompt mapping with generic blocked/unavailable text;
- prompt construction without Runner request or readiness wait;
- shared bounded matching-Runtime resolver for tools, file storage, Workspace
  browser, TurnActions, worktrees, and transfers;
- current-qualified `READY` and `BUSY` target semantics;
- explicit operation-attributed wait progress, timeout, cancellation, and
  generation fencing;
- derived containment capability/application/availability server projections;
- Admin and Workspace Runtime Profile/API/Web consumption;
- regenerated OpenAPI and Python/TypeScript clients.

Removal obligations:

- instantaneous TurnAction `runner_state == READY` failure;
- caller-specific literal-READY checks and duplicate polling;
- Runtime prompt without typed desired-Profile behavior;
- any proposed persisted containment status.

Validation:

- backend prompt/readiness/projection unit and service tests;
- OpenAPI generation and generated clients;
- TypeScript format, lint, typecheck, build, and meaningful Storybook states;
- model-dispatch-without-Runner and explicit-operation-wait product E2E.

## Phase 7 — Validation, Specs, snapshot promotion, and cleanup

Approved mechanisms: `M12` and verification of `M1` through `M13`.

Deliver:

- complete Docker and Kubernetes E2E matrix;
- complete backend conformance evidence;
- full security canary and removal absence evidence;
- Design Authority drift audit against the final stack;
- current living Spec updates through `/spec-review`;
- matching `implemented: 2026-08-08` dates on Requirements and Design only after
  complete validation;
- removal of this implementation plan and all seven phase plans.

Validation:

- all affected Python project quality suites;
- TypeScript format, lint, typecheck, and build;
- generated artifact drift checks;
- deterministic Docker and Kubernetes Runtime E2E;
- testenv unit and relevant E2E lanes;
- snapshot/spec validation and final `git diff --check`.

## Removal obligation assignment

| Removal | Owning phase | Absence evidence |
| --- | --- | --- |
| Profile-v1-only contract assumptions | 1 | v1/v2 parser and compatibility tests; static search |
| Direct process subprocess authority | 2 | operation-handler static search; process conformance |
| `os.environ.copy()` Agent environment | 2 | static search; Runner-secret canary |
| Direct backend-specific process calls | 2 | import/command construction boundary tests |
| Trusted native file/Git/transfer path access | 3 | static search; shell/native parity E2E |
| Shared Agent/Runner temporary authority | 3, 4, 5 | provider mount inspection and canary E2E |
| Docker implicit contained security | 4 | create/inspect contract assertions |
| Kubernetes DinD-only temporary behavior | 5 | resource rendering and real Pod inspection |
| Instantaneous TurnAction readiness failure | 6 | slow-start TurnAction E2E |
| Caller-specific readiness polling | 6 | shared-resolver call-site search and tests |
| Runtime prompt without Profile behavior | 6 | prompt snapshots and no-readiness-call tests |
| Persisted containment state | 6 | schema absence and derived projection tests |
| Temporary implementation plans | 7 | repository path absence after cleanup |

## Integration and context checkpoints

At every phase boundary record:

- completed approved mechanisms and requirements;
- changed interfaces and generated surfaces;
- removal obligations completed and absence evidence;
- validation commands and results;
- independent reviewer findings and correction status;
- Design delta confirmation;
- remaining phases, risks, and prerequisites; and
- branch, base, commit, and PR.

The next phase starts only after the current phase PR exists. CI monitoring starts
only after all seven PRs exist.

## Spec impact

Expected living Spec updates include:

- `spec/domain/runtime-provider.md`;
- `spec/domain/toolkit.md`;
- `spec/domain/agent.md` and `spec/domain/workspace.md` where derived projections
  are documented;
- `spec/flow/agent-runtime-control.md`;
- `spec/flow/agent-runtime-persistence.md`;
- `spec/flow/agent-execution-loop.md`; and
- `spec/flow/test-strategy-e2e-primary.md`.

Final scope is determined by `/spec-review` against the stable implementation diff.

## External prerequisites and operational boundaries

- No live Kubernetes, Argo CD, production Provider, or database change is performed.
- Docker E2E uses the repository's deterministic Runtime Provider fixture.
- Kubernetes E2E adds a disposable local/CI cluster fixture with no external
  credentials.
- Public internet is not a test prerequisite; egress uses deterministic local or
  in-cluster endpoints.
- Provider capability remains disabled until its real environment conformance
  succeeds.

## Blockers

No current Design blocker is known. A new material behavior, authority, fallback,
configuration mode, or source of truth returns to `feature-design` and requires
Design revision and approval before implementation continues.

## Plan cleanup

Phase 7 removes this plan and every
`runtime-260808-provider-process-containment-phase-*.md` execution plan after
validation and Spec promotion. Requirements, ADR, approved Design, current Specs,
code, tests, and PR history remain as the durable sources of truth.
