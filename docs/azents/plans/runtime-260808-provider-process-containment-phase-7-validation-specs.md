---
title: "Provider-Owned Runtime Process Containment Phase 7 Validation and Specs Plan"
created: 2026-08-09
updated: 2026-08-09
tags: [runtime, validation, e2e, security, specification, cleanup]
---

# Provider-Owned Runtime Process Containment Phase 7 Validation and Specs Plan

## Phase Execution Plan

- Phase: `7 — Integration validation, living Specs, snapshot promotion, and cleanup`
- Branch/base:
  `azents/runtime-containment-7-validation-specs` →
  `azents/runtime-containment-6-worker-surfaces`
- PR boundary: Final cross-phase authority, conformance, security, generated-artifact,
  and product validation; promotion of current behavior into living Specs; matching
  implementation dates on the approved snapshot; and deletion of temporary feature
  plans.
- Inputs: Completed Profile contracts, Runner backend and contained operations,
  Docker and Kubernetes Provider preparation, Worker prompt/readiness integration,
  derived API/UI surfaces, generated clients, and phase-level review evidence from
  phases 1 through 6.
- Deliverables:
  - deterministic Docker and disposable Kubernetes containment evidence for the
    implemented Profile, Provider, Runner, operation, prompt, and readiness contract;
  - complete backend/frontend/generated-artifact quality evidence for the stable
    seven-phase stack;
  - a final Design Authority and removal audit covering `M1` through `M13` and every
    authoritative removal without adding a new mechanism;
  - `/spec-review`-grounded living Spec updates that describe current contained and
    retained uncontained behavior, derived projections, E2E policy, and authority;
  - matching `implemented: 2026-08-09` frontmatter on the Requirements and Design
    after validation succeeds;
  - deletion of the feature implementation plan and all seven phase execution plans.
- Non-goals:
  - a new containment mode, backend, fallback, policy surface, lifecycle authority,
    persistence model, compatibility path, or product behavior;
  - editing the accepted ADR or rewriting the Design as a living document;
  - live Kubernetes, Argo CD, production Provider, database, or deployment mutation;
  - replacing unavailable deterministic evidence with a claimed pass;
  - merging the stack or monitoring per-PR CI before this seventh PR exists.
- Interfaces:
  - approved `runtime-260808/REQ`, append-only `runtime-260808/ADR`, and
    `runtime-260808/DESIGN` revision 2 with authority `M1` through `M13`;
  - complete phase 1–6 stacked diff based on
    `azents/runtime-containment-6-worker-surfaces`;
  - current living Spec frontmatter, `code_paths`, and current-behavior rules;
  - required deterministic Docker Runtime Provider and disposable Kubernetes
    containment CI lanes plus repository quality commands.
- Approved Design mechanisms: `M12` and verification of `M1` through `M13`.
- Authority references:
  - `runtime-260808/REQ-1` through `REQ-16`;
  - `runtime-260808/ADR-D1` through `ADR-D11`;
  - `runtime-260808/DESIGN` revision 2, especially Test Strategy, Removal and
    Replacement, Design Authority, Authority Audit, and Design Approval;
  - current Runtime Provider, Runtime control/persistence, Toolkit, Agent,
    Workspace, execution-loop, and E2E living Specs.
- Design delta: `None`
- Removal obligations:
  - delete the temporary multi-phase implementation plan and phase 1–7 execution
    plans after validation and Spec promotion;
  - verify the earlier phase removals remain absent across the final integrated
    stack: direct trusted Agent process/file/Git/transfer authority, inherited
    Runner environment, shared Agent/Runner temporary authority, caller-specific
    Runtime readiness, Profile-v1-only assumptions, and persisted containment state.
- Absence verification:
  - repository searches and targeted review prove no direct Agent subprocess,
    trusted native path/Git/transfer, `os.environ.copy()`, caller-owned readiness
    loop, literal-`READY` qualification, containment persistence, backend argument,
    DinD mixing, or weaker fallback remains;
  - Provider/Runner resource and conformance evidence proves separated temporary
    views, non-root UID/GID 1000 children, capability-free execution, no protected
    credential/socket/path access, and no containment advertisement without
    enforceable qualification;
  - repository path checks prove all `runtime-260808-provider-process-containment-*.md`
    plans are absent from the final phase diff.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Cross-phase authority and removal audit | `/root` | Complete stack diff, Requirements, ADR, Design, source and test paths from phases 1–6 | Stable Phase 6 head and phase review records | Forward/reverse traceability, unauthorized-mechanism result, removal absence evidence | Targeted searches, diff inspection, independent reviewer verdict |
| Backend and generated contracts | `/root` | Affected Python projects, OpenAPI specs, generated Python/TypeScript clients | Stable source schemas and generation commands | Passing quality suites and synchronized generated artifacts | Ruff, format, `ty`, pytest, OpenAPI dump, client generation/drift checks |
| Provider and containment conformance | `/root` | Runner, Docker Provider, Kubernetes Provider, Helm, testenv and CI fixture paths | Qualified local container/runtime prerequisites | Docker and disposable Kubernetes enforcement evidence with bounded diagnostics | Backend conformance, provider tests, image/chart checks, required E2E scripts or CI evidence |
| Product surfaces | `/root` | Main Web and Admin Web packages, stories and localized messages | Generated clients and server-derived projections | Passing presentation and build checks without frontend authority recomputation | Format, lint, typecheck, tests, production builds, Storybook build |
| Living Spec promotion | `/root` | `/docs/azents/spec/domain/**`, `/docs/azents/spec/flow/**` matched by `/spec-review` | Stable implementation and completed validation | Current behavior, authority, failure, compatibility, and E2E policy recorded with refreshed verification dates | Spec review, source-to-spec comparison, snapshot/frontmatter validation |
| Snapshot promotion and cleanup | `/root` | Runtime containment Requirements/Design frontmatter and all feature plans | All validation and review complete | Matching implementation date and no temporary plans | Snapshot validator, plan absence search, pre-commit, `git diff --check` |

- Integration order:
  1. Freeze the Phase 6 head and inventory the complete stack diff and applicable
     validation commands.
  2. Run deterministic backend, Provider, E2E, generated-artifact, and frontend
     validation; record prerequisites, results, and bounded failures.
  3. Fix only discovered integration defects within approved authority, rerun
     invalidated checks, and request targeted re-review when required.
  4. Audit `M1` through `M13`, all Requirements, and every Removal and Replacement
     entry against the stable integrated code and tests.
  5. Run `/spec-review`, update only impacted current Specs, and independently compare
     their bodies and `code_paths` with the implementation.
  6. After validation and review pass, add matching implementation dates to
     Requirements and Design and delete all temporary feature plans.
  7. Run snapshot/spec validation, pre-commit, final diff/security review, commit,
     push, and create the seventh stacked PR before beginning stack-wide CI monitoring.
- Independent review:
  `/root/runtime-containment-reviewer` performs a read-only review against all
  confirmed Requirements, accepted ADR decisions, Design revision 2 authority,
  Removal and Replacement entries, this phase contract, current Specs, validation
  evidence, and the final diff. The reviewer reports only grounded Critical or
  Warning findings, with priority on missing or unauthorized behavior, security
  boundary regression, false validation claims, stale/incomplete Specs, mismatched
  implementation dates, and incomplete plan cleanup.
- Final validation:
  - affected Python project Ruff, format, `ty --error-on-warning`, focused and full
    pytest suites;
  - Runner/Docker/Kubernetes conformance tests, Docker image/build probes, Helm render
    tests, and disposable Kubernetes containment script when the local prerequisite
    is available, otherwise required CI evidence without claiming a local pass;
  - OpenAPI dump, Python and TypeScript client generation, generated drift checks,
    and generated Python client suites;
  - TypeScript format, lint, typecheck, focused tests, production builds, and
    Storybook build for Main Web and Admin Web;
  - testenv unit tests and affected deterministic Runtime Provider/Web E2E lanes;
  - snapshot/spec validators, plan/removal absence searches, pre-commit hooks, and
    `git diff --check`.
- Scope-drift check:
  confirm all `REQ-1` through `REQ-16` and `M1` through `M13` are implemented and
  tested, all accepted removals are complete, and the final diff adds no material
  mechanism, authority, fallback, state, configuration, compatibility mode, or
  product contract absent from approved Design revision 2. Any such finding returns
  to feature design rather than being documented as an implementation detail.
- Context checkpoint:
  phases 1–6 are complete and independently reviewed, their stacked PRs exist through
  #1215, and their focused/full quality evidence passed at each stable phase head.
  Phase 7 owns only final integrated evidence, current Spec promotion, snapshot
  completion, and temporary-plan deletion. The remaining risks are environmental
  Docker/Kubernetes prerequisites, generated-artifact drift, an integrated authority
  or removal gap hidden by phase boundaries, and over- or under-documenting current
  behavior. No live infrastructure action or PR merge is authorized.
