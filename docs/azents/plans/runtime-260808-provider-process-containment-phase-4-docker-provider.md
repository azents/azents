---
title: "Provider Process Containment Phase 4 Docker Provider Execution Plan"
created: 2026-08-08
updated: 2026-08-09
tags: [runtime, provider, docker, security, containment, implementation]
---

# Phase Execution Plan

- Phase: `4 — Docker Provider integration`
- Branch/base:
  `azents/runtime-containment-4-docker-provider` →
  `azents/runtime-containment-3-contained-operations`
- PR boundary: Allow the bundled Docker Runtime Provider to advertise and prepare
  Docker Container Profile v2 process containment only when its trusted deployment
  configuration selects the supported bwrap backend, then create and observe one
  fail-closed contained Runner container with separate Workspace, Agent temporary,
  and Runner-private authority while preserving Docker Profile v1 behavior.
- Inputs:
  - Phase 3 commit `48268430b` and PR `#1212`;
  - confirmed `runtime-260808/REQ`;
  - accepted `runtime-260808/ADR-D1` through `ADR-D11`;
  - `runtime-260808/DESIGN` revision 2 and authority IDs `M1` through `M13`;
  - Phase 1 typed `DockerContainerProfileV2` and portable
    `RuntimeProcessContainmentModuleV1` contracts;
  - Phase 2 Runner bootstrap parser, selected direct/bwrap backend, positive
    projection, qualification, bounded failure categories, and pre-registration
    fail-closed lifecycle;
  - Phase 3 contained native operation/helper boundary and production Runner
    image;
  - current Docker Provider lifecycle, immutable configuration evidence,
    recreation, Workspace persistence, API adapter, registration capability
    contract, and Runtime Provider E2E substrate.
- Deliverables:
  - one trusted Docker Provider deployment setting that either disables
    containment advertisement or selects the supported bwrap preparation class;
  - Docker capability registration that advertises
    `docker.container-profile` schema version 2 and
    `runtime.process-containment` only when that deployment setting is valid
    and Docker daemon security-option evidence confirms AppArmor support;
  - acceptance of Docker Profile v2 without containment as the v1-equivalent
    physical container contract and acceptance of its containment module only
    when the Provider deployment can prepare the selected backend;
  - contained Runner bootstrap JSON with the exact schema, bwrap backend,
    Runner-reported Workspace mount, hidden Agent temporary backing path,
    Runner-private paths, and bounded qualification timeout;
  - separate Runtime-specific host directories and container mounts for durable
    Workspace, ephemeral Agent temporary backing, and Runner-private temporary
    state, with Agent temporary projected to `/tmp` only by the Runner backend;
  - explicit Docker create and inspect contracts for trusted Runner user,
    capability add/drop, compatible security profile/user-namespace/system-path
    preparation, read/write mount intent, and stable terminal diagnostics;
  - fail-closed container reuse/recreation comparison covering Profile version,
    containment bootstrap, mounts, and security settings without mutating or
    downgrading a contained Profile;
  - bounded Provider observation of Runner container exit status needed to
    attribute pre-registration qualification failure without exposing raw logs,
    environment, mount inventories, or secrets;
  - deterministic Docker Provider tests and real-provider E2E proving
    qualification success/failure, UID/GID and capability invariants, positive
    path projection, private canaries, Workspace preservation, Agent temporary
    lifecycle, ordinary outbound connectivity, and rollback to an explicit
    non-contained Profile.
- Non-goals:
  - Kubernetes Provider resources, RuntimeClass, Pod security, EmptyDir,
    NetworkPolicy, service-account, Helm, or cluster E2E work;
  - Worker prompt/readiness/resolver, Runtime API/status projection, Admin or
    Workspace Web, OpenAPI/client generation, or Living Spec promotion;
  - changing Runner containment mechanisms, helper protocol, operation/transfer
    contracts, Control protobufs, configuration evidence, or Runtime lifecycle
    state machines;
  - combining containment with DinD, projecting a Docker socket, claiming
    Kubernetes-equivalent network enforcement, adding raw Profile-authored
    sandbox arguments, introducing a fallback backend, or making containment the
    default Profile.
- Interfaces:
  - Docker Profile v1 remains byte-for-byte behaviorally unchanged and never
    receives containment bootstrap or containment capability claims;
  - Docker Profile v2 without a containment module uses the existing direct
    Runner behavior and remains compatible only with its declared v2 contract;
  - Docker Profile v2 with containment is accepted only when Provider deployment
    configuration selects the supported preparation class and Docker daemon
    security-option evidence confirms AppArmor support; otherwise Provider
    startup fails before compatibility advertisement and direct command handling
    rejects it;
  - Provider bootstrap uses the Runner-owned
    `AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG` schema and contains no
    Profile-authored backend arguments or Agent/model-visible data;
  - Agent temporary backing is mounted at a fixed Runner-private absolute path;
    contained execution maps that backing path to `/tmp`, while Runner `/tmp`
    and other private paths are not projected;
  - the trusted Runner container remains UID/GID 1000, receives no
    Agent-accessible Docker socket, drops all workload capabilities and adds only
    `CAP_SYS_ADMIN`, `CAP_SYS_CHROOT`, `CAP_NET_ADMIN`, `CAP_SETUID`,
    `CAP_SETGID`, `CAP_SYS_PTRACE`, and `CAP_SETPCAP` for the root-owned
    set-user-ID bwrap bootstrap, while every contained Agent child is UID/GID
    1000 with zero capabilities, `NoNewPrivs=1`, and nested user namespaces
    denied;
  - Docker create and inspect typed structures carry every security and terminal
    field used for reuse or failure decisions; raw Docker JSON is decoded only at
    the adapter boundary;
  - a Runner that exits before registration is reported through existing bounded
    Provider observed state/reason/diagnostic surfaces; no new durable
    qualification state is introduced;
  - physical Profile adoption/removal and rollback use existing Runtime
    recreation, preserve durable Workspace storage, and treat Agent temporary as
    disposable.
- Target Design mechanisms: `M2`, `M5`, `M11`, `M12`, `M13`
- Authority references:
  `runtime-260808/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`,
  `REQ-7`, `REQ-8`, `REQ-9`, `REQ-10`, `REQ-11`, `REQ-12`, `REQ-13`,
  `REQ-14`; `runtime-260808/ADR-D1`, `ADR-D2`, `ADR-D3`, `ADR-D5`,
  `ADR-D6`, `ADR-D8`, `ADR-D9`, `ADR-D10`, `ADR-D11`;
  `runtime-260808/DESIGN` revision 2; current
  `spec/domain/runtime-configuration.md`,
  `spec/flow/agent-runtime-control.md`, `spec/domain/workspace.md`, and
  `spec/flow/test-strategy-e2e-primary.md`.
- Design delta: `None`
- Removal obligations:
  - remove the current Docker `/tmp/agent` bind as the contained Profile's shared
    Agent/Runner temporary authority and replace it with a hidden Agent temporary
    backing mount plus private Runner temporary state;
  - remove implicit/default Docker security behavior as authority for contained
    Profiles by carrying and validating explicit security create/inspect fields;
  - prevent v1-only capability registration from being the Docker Provider's
    containment availability source once a compatible deployment is enabled;
  - retain the existing v1 path only as explicit non-contained behavior, never as
    fallback for a failed or unsupported contained Profile.
- Absence verification:
  - contained Docker specs contain no Docker socket/DinD mount and no shared
    `/tmp/agent` container bind;
  - contained bootstrap and positive bwrap projection are the only path from the
    hidden Agent temporary backing directory to Agent `/tmp`;
  - container create/inspect tests prove the trusted Runner has only the exact
    bootstrap capability set, security preparation is explicit, and reuse rejects
    user/security/bootstrap drift;
  - real qualification proves every Agent child has UID/GID 1000, all capability
    sets zero, `NoNewPrivs=1`, and nested user namespaces denied;
  - capability contract snapshots prove schema v2 and
    `runtime.process-containment` are absent when deployment preparation is
    disabled and present only when enabled;
  - injected missing/backend-failure journeys prove no Runner registration and no
    direct fallback;
  - repository/static checks find no containment work in the Kubernetes Provider,
    Worker/API/Web surfaces, Control protobufs, or Living Specs in this phase.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan | `/root` | `docs/azents/plans/runtime-260808-provider-process-containment-phase-4-docker-provider.md` | Phase 3 PR | Tracked Phase 4 scope and interfaces | Documentation validation, `git diff --check` |
| Deployment and capability contract | `/root` | `python/apps/azents-runtime-provider-docker/src/azents_runtime_provider_docker/main.py`; settings tests | Phase 1 v2 contracts | Explicit preparation setting and conditional v2/capability registration | Settings and registration contract tests, Ruff, ty |
| Docker lifecycle preparation | `/root` | `python/apps/azents-runtime-provider-docker/src/azents_runtime_provider_docker/provider.py`; provider tests | Phase 2 bootstrap and Phase 3 image | Typed v1/v2 validation, contained env/mount/storage/recreation/diagnostic behavior | Provider lifecycle, rollback, preservation, failure tests |
| Docker API security boundary | `/root` | `python/apps/azents-runtime-provider-docker/src/azents_runtime_provider_docker/{docker_api,aiodocker_api}.py`; adapter tests | Lifecycle container spec | Explicit create/inspect security and terminal fields | Adapter request/response contract tests against fakes and Docker |
| Docker product E2E | `/root` | focused `testenv/azents/e2e/src/tests/**/runtime*` and support/fixture paths only when required | Production Provider and Runner images | Real contained Profile adoption, qualification, operations, failure, temporary lifecycle, connectivity, rollback evidence | Credential-free Runtime Provider E2E lane and Docker diagnostics |
| Independent review | `/root/runtime-containment-reviewer` | Read-only complete Phase 4 diff | Stable implementation and validation | Requirements/security/Provider/recreation/removal findings | Reviewer report or explicit no findings |

- Integration order:
  1. Commit this Phase 4 execution plan before implementation.
  2. Add trusted deployment settings and conditional capability-contract
     construction without changing the disabled/v1 registration snapshot.
  3. Extend typed Docker create/inspect contracts with explicit security,
     bootstrap, mount, and terminal evidence.
  4. Accept Docker Profile v2, derive contained versus direct preparation, create
     separate host/storage paths, and emit exact Runner bootstrap input.
  5. Make reuse/recreation and observation compare all contained physical
     authority and report bounded pre-registration terminal failure.
  6. Add focused unit/adapter coverage for conditional advertisement, v1 parity,
     v2 direct behavior, contained success, missing preparation, security drift,
     Workspace preservation, temporary loss, rollback, and diagnostic bounds.
  7. Build production Provider and Runner images and run real Docker backend
     qualification/conformance and product E2E without starting Kubernetes or
     later-phase Worker/API/Web work.
  8. Run complete Docker Provider, affected runtime-control/Runner contract,
     testenv E2E, image, static removal, documentation, and scope-drift
     validation.
  9. Request independent review from `/root/runtime-containment-reviewer`, batch
     required corrections, rerun affected evidence, and request targeted
     re-review only for material findings.
  10. Commit and open PR 4 against the Phase 3 branch before creating Phase 5.
- Independent review:
  - Reviewer: `/root/runtime-containment-reviewer`.
  - Scope: complete Phase 4 diff.
  - Criteria: conditional and honest capability advertisement; no contained-v1
    fallback; exact trusted bootstrap; no Docker socket/DinD; separate Workspace,
    Agent temporary, and Runner-private authority; explicit secure create/inspect
    contract; non-root Runner and restricted set-user-ID bwrap bootstrap
    authority; Agent-child
    UID/GID 1000 and capability/no-new-privileges/user-namespace invariants;
    Provider-managed network preservation; bounded pre-registration
    failure; recreation/rollback and Workspace/temporary semantics; no secrets or
    raw sandbox data in diagnostics; no Kubernetes, Worker, API, Web, protobuf,
    Spec-promotion, or new state drift; completed removal obligations; `Design
    delta: None`.
  - Inputs: Requirements, accepted ADR, Design revision 2,
    multi-phase plan, Phase 1-3 contracts and PRs, this phase plan, current Specs,
    complete diff, capability snapshots, Docker create/inspect evidence, real
    qualification/E2E evidence, static absence output, and validation results.
  - Output: grounded Critical/Warning findings or explicit no findings.
- Final validation:
  - `cd python/apps/azents-runtime-provider-docker && uv run ruff format --check src tests`
  - `cd python/apps/azents-runtime-provider-docker && uv run ruff check src tests`
  - `cd python/apps/azents-runtime-provider-docker && uv run ty check --error-on-warning`
  - `cd python/apps/azents-runtime-provider-docker && uv run pytest -q`
  - affected `azents-runtime-control` and Runtime Runner contract tests
  - Docker API adapter create/inspect tests and production Provider/Runner image builds
  - real Docker bwrap qualification and backend conformance suite
  - credential-free focused Runtime Provider E2E with captured Docker diagnostics
  - conditional capability-contract snapshots and Profile v1/v2 compatibility tests
  - static removal/absence checks described above
  - documentation validation and `git diff --check`
- Scope-drift check:
  Confirm the diff implements only `M2`, `M5`, `M11`, `M12`, and `M13` for the
  Docker Provider. Remove Kubernetes resources, Worker readiness/prompt/resolver, API/Web,
  OpenAPI/generated-client, protobuf, Living Spec promotion, durable qualification
  state, Profile-authored backend arguments, containment defaults, DinD coexistence,
  network-equivalence claims, compatibility fallback, or Runner helper/backend
  mechanism changes.
- Context checkpoint:
  Record deployment setting and conditional capability contract, Docker Profile
  v1/v2 handling, bootstrap schema and exact paths, host/container storage and
  mount model, explicit security create/inspect fields, reuse and recreation
  authority, bounded terminal diagnostics, Workspace/temporary/rollback evidence,
  image and real-provider E2E evidence, reviewer findings and corrections,
  branch/base/commit/PR, and exact Phase 5 Kubernetes Provider inputs.
