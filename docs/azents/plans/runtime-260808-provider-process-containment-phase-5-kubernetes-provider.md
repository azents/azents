---
title: "Provider Process Containment Phase 5 Kubernetes Provider Execution Plan"
created: 2026-08-09
updated: 2026-08-09
tags: [runtime, provider, kubernetes, security, containment, implementation]
---

# Phase Execution Plan

- Phase: `5 — Kubernetes Provider integration`
- Branch/base:
  `azents/runtime-containment-5-kubernetes-provider` →
  `azents/runtime-containment-4-docker-provider`
- PR boundary: Allow the bundled Kubernetes Runtime Provider to advertise and
  prepare Kubernetes Pod Profile v2 process containment only when trusted
  deployment configuration selects the supported bwrap preparation class, then
  create and observe fail-closed contained Runner Pods with durable Workspace,
  ephemeral Agent temporary, and Runner-private authority while preserving
  Kubernetes Profile v1 and direct v2 behavior.
- Inputs:
  - Phase 4 commit `2b03be415` and PR `#1213`;
  - confirmed `runtime-260808/REQ`;
  - accepted `runtime-260808/ADR-D1` through `ADR-D11`;
  - approved `runtime-260808/DESIGN` revision 2 and authority IDs `M1` through
    `M13`;
  - Phase 1 typed `KubernetesPodProfileV2` and portable
    `RuntimeProcessContainmentModuleV1` contracts;
  - Phase 2 non-root Runner, root-owned mode-4755 bwrap, Runner-owned nested-userns
    seccomp launcher, backend qualification, and fail-closed pre-registration
    lifecycle;
  - Phase 3 contained native operation/helper boundary and positive projection;
  - Phase 4 exact seven-capability bwrap bootstrap, bounded diagnostics, and
    AppArmor-independent Docker qualification evidence;
  - current Kubernetes Provider lifecycle, typed Pod/PVC/NetworkPolicy resources,
    immutable configuration evidence, recreation, watch reporting, Workspace
    persistence, Helm deployment, RBAC, and render tests.
- Deliverables:
  - trusted Kubernetes deployment settings that either disable containment or
    select the supported bwrap preparation class, exact localhost AppArmor
    profile, bounded qualification timeout, and optional compatible RuntimeClass;
  - Kubernetes capability registration that advertises
    `kubernetes.pod-profile` schema version 2 and
    `runtime.process-containment` only when deployment preparation is valid;
  - direct Kubernetes Profile v2 without containment as the existing v1-equivalent
    Pod contract within a v2-capable deployment;
  - startup validation of a configured RuntimeClass object before capability
    registration, with the default RuntimeClass retained when no name is selected;
  - contained Runner bootstrap JSON using the shared Runner-owned schema, exact
    Workspace mount, hidden Agent temporary backing path, Runner-private paths,
    and bounded qualification timeout;
  - separate Agent temporary and Runner-private `EmptyDir` volumes for contained
    Pods while retaining the durable Workspace PVC;
  - contained Runner container security with UID/GID 1000,
    `allowPrivilegeEscalation: true`, `runAsNonRoot: true`, `capabilities.drop:
    [ALL]`, the exact seven bwrap bootstrap capabilities, unconfined seccomp,
    unmasked proc, exact localhost AppArmor profile, and no privileged container;
  - optional trusted RuntimeClass lowering only for contained Pods, with explicit
    incompatible/missing class failure and no fallback to another class or direct
    execution;
  - typed manifest and decoder support for every Pod/container security field used
    by create, inspect, reuse, and recreation decisions;
  - bounded pre-registration Pod/container termination diagnostics containing only
    safe status, exit-code, reason, and OOM evidence;
  - Helm values and Provider Deployment environment wiring for the opt-in
    preparation settings while default installation behavior remains disabled;
  - deterministic Provider/resource/Helm tests and a disposable real-cluster
    conformance path proving qualification, Pod security, positive projection,
    temporary lifecycle, Workspace preservation, outbound policy behavior, and
    rollback.
- Non-goals:
  - Docker Provider changes beyond inherited Phase 4 behavior;
  - Worker prompt/readiness/resolver, Runtime API/status projection, Admin or
    Workspace Web, OpenAPI/client generation, or Living Spec promotion;
  - Profile-authored backend arguments, RuntimeClass names, AppArmor profiles,
    seccomp settings, capabilities, or qualification timeouts;
  - privileged Runner Pods, root Runner identity, pure-unprivileged bwrap,
    file-capability bwrap, subordinate-ID helpers, direct fallback, gVisor support,
    DinD combination, or Agent-visible service-account tokens;
  - writes to the connected `home` Kubernetes cluster or any live infrastructure.
- Interfaces:
  - Kubernetes Profile v1 remains behaviorally unchanged and never receives a
    containment bootstrap or containment capability claim;
  - Kubernetes Profile v2 without a containment module uses the existing direct
    Runner Pod behavior in a deployment that advertises v2;
  - Kubernetes Profile v2 with containment is accepted only when Provider
    deployment configuration selects the supported preparation class; otherwise
    Provider compatibility does not advertise it and direct command handling
    rejects it;
  - deployment settings, never the portable Profile, select backend `bwrap`, exact
    localhost AppArmor profile `azents-runtime-bwrap`, qualification timeout, and
    optional RuntimeClass name;
  - a configured RuntimeClass must exist before Provider registration; an omitted
    name uses the cluster default and relies on fail-closed Runner qualification;
  - contained Pod preparation uses `seccompProfile.type: Unconfined`,
    `procMount: Unmasked`, and `appArmorProfile.type: Localhost` with the exact
    supported profile; admission or runtime rejection remains terminal and never
    downgrades security;
  - the Runner process remains UID/GID 1000 with no effective, permitted,
    inheritable, or ambient capabilities; the root-owned set-user-ID bwrap receives
    only `SYS_ADMIN`, `SYS_CHROOT`, `NET_ADMIN`, `SETUID`, `SETGID`, `SYS_PTRACE`,
    and `SETPCAP` through the container bounding set;
  - every contained Agent child remains UID/GID 1000 with all capability sets zero,
    `NoNewPrivs=1`, nested user namespaces denied, and the privileged bwrap inode
    hidden;
  - Agent temporary backing is mounted at `/run/azents/agent-tmp` and projected to
    Agent `/tmp` only by bwrap; Runner-private state is mounted at
    `/run/azents/runner-private` and is not projected;
  - Workspace PVC survives Pod recreation; Agent temporary and Runner-private
    EmptyDir state is discarded with each replacement Pod;
  - no service-account token is automatically mounted into Runtime Pods;
  - existing NetworkPolicy authority and Profile scheduling remain unchanged;
    containment adds no alternate egress authority;
  - raw Kubernetes JSON is decoded into typed Pod/container evidence only at the
    Kubernetes HTTP boundary.
- Approved Design mechanisms: `M2`, `M5`, `M11`, `M12`, `M13`
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
  - remove DinD-only shared temporary volume behavior as the only Kubernetes path
    to separately backed Agent temporary storage;
  - remove implicit/default Kubernetes container security as authority for
    contained Profiles by carrying and validating explicit typed fields;
  - prevent the fixed v1 capability contract from advertising Kubernetes
    containment when deployment preparation is disabled or invalid;
  - retain direct v1/v2 only as explicit non-contained behavior, never as fallback
    for a failed contained Profile.
- Absence verification:
  - contained Pod specs contain no DinD engine sidecar, engine socket, shared DinD
    `/tmp`, privileged Runner, root Runner, or service-account-token mount;
  - the contained bootstrap and positive bwrap projection are the only path from
    the hidden Agent temporary EmptyDir to Agent `/tmp`;
  - manifest/decoder/reuse tests prove every required security field and
    RuntimeClass choice round-trips and security drift forces replacement;
  - static searches prove no Profile-authored backend/security arguments and no
    direct fallback were added;
  - real-cluster inspection proves the final Agent child cannot see Runner-private
    paths, the privileged bwrap inode, nested user namespaces, or capabilities.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan and authority traceability | `/root` | `docs/azents/plans/runtime-260808-provider-process-containment-phase-5-kubernetes-provider.md` | Phase 4 checkpoint, approved Design | Tracked Phase 5 scope with `Design delta: None` | Plan completeness and `git diff --check` |
| Kubernetes typed resource boundary | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/kubernetes_api.py`, `kubernetes_http.py`; adapter tests | Existing typed Pod model | RuntimeClass, proc mount, seccomp, AppArmor, and termination evidence round-trip | Focused HTTP manifest/decoder pytest, Ruff, ty |
| Provider preparation and lifecycle | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/provider.py`; Provider tests | Typed resource boundary, Profile v2 | Bootstrap, EmptyDirs, security context, reuse/recreation, diagnostics, fail-closed validation | Provider pytest and absence assertions |
| Deployment settings and registration | `/root` | `python/apps/azents-runtime-provider-kubernetes/src/azents_runtime_provider_kubernetes/main.py`; settings tests | Provider preparation contract | Conditional v2 advertisement and RuntimeClass preparation gate | Settings/control-loop pytest, Ruff, ty |
| Helm preparation wiring | `/root` | `infra/charts/azents/values.yaml`, `infra/charts/azents/templates/runtime-provider-kubernetes/**`, `infra/charts/azents/tests/runtime_provider_kubernetes_render_test.py` | Settings names and defaults | Opt-in values/env/RBAC with disabled default | Helm render tests and chart lint |
| Disposable cluster conformance | `/root` | `.github/workflows/ci.yaml`, `testenv/azents/e2e/**`, bounded support manifests/scripts | Provider and Helm integration, Runner image | Required Linux cluster qualification and contained product E2E | Disposable kind cluster, JUnit, safe logs |

- Integration order:
  1. add and validate the tracked Phase 5 plan;
  2. extend typed Kubernetes resource and HTTP round-trip contracts;
  3. add trusted settings and conditional capability registration;
  4. lower Profile v2 containment into bootstrap, volumes, security context,
     RuntimeClass, reuse, lifecycle, and diagnostics;
  5. add Helm opt-in preparation and render/RBAC coverage;
  6. add disposable-cluster qualification and product E2E;
  7. run independent security review, correct grounded findings, and execute final
     integration validation.
- Independent review: `/root/runtime-containment-reviewer` performs one read-only
  review against `runtime-260808/REQ`, accepted ADR-D1 through ADR-D11, approved
  Design revision 2/M2/M5/M11/M12/M13, this phase plan, and the final Phase 4 to
  Phase 5 diff. Criteria: honest conditional advertisement; exact non-root setuid
  bwrap bootstrap; no privileged/root/DinD fallback; typed security round-trip and
  drift replacement; separate temporary authority; service-account isolation;
  RuntimeClass/security-policy failure; bounded diagnostics; Workspace preservation;
  v1/direct-v2 regression safety; cluster fixture trustworthiness; no unrelated
  Phase 6/7 scope. Output is grounded Critical/Warning findings or explicit no
  findings.
- Final validation:
  - `cd python/apps/azents-runtime-provider-kubernetes && uv run pytest -q`;
  - `cd python/apps/azents-runtime-provider-kubernetes && uv run ruff format --check src tests`;
  - `cd python/apps/azents-runtime-provider-kubernetes && uv run ruff check src tests`;
  - `cd python/apps/azents-runtime-provider-kubernetes && uv run ty check --error-on-warning`;
  - focused Runner qualification/conformance tests if shared bootstrap assumptions
    change;
  - Helm render tests and chart lint;
  - Kubernetes Provider and Runner image builds;
  - disposable-cluster contained qualification/E2E with Pod inspection;
  - `git diff --check` and static absence searches.
- Scope-drift check: The phase must cover M2/M5/M11/M12/M13 Kubernetes lowering,
  removal obligations, and required cluster evidence. It must not add Worker/API/Web
  behavior, Profile fields, backend selection by Profile, new lifecycle state,
  persisted containment status, fallback, gVisor compatibility, Docker changes, or
  live-cluster mutation. New product behavior or material security modes return to
  Requirements/ADR/Design; local equivalent Kubernetes field and fixture details
  remain owner decisions.
- Context checkpoint: Phase 4 established the shared non-root setuid bwrap contract,
  exact seven-capability bootstrap, Agent-child zero-capability/NoNewPrivs/nested-
  userns invariants, positive projection, bounded diagnostics, conditional
  advertisement, and honest AppArmor preparation evidence. Phase 5 must prove the
  same child authority through Kubernetes Pod lowering without DinD, privileged
  Runner, root Runner, service-account authority, direct fallback, or live cluster
  changes. Relevant paths are the Kubernetes Provider typed API/HTTP boundary,
  lifecycle provider, settings/registration, Helm chart, and disposable E2E. Main
  risks are Kubernetes/CRI support for unmasked proc and localhost AppArmor,
  cluster RuntimeClass compatibility, and trustworthy disposable-cluster evidence;
  each fails closed rather than weakening the boundary.
