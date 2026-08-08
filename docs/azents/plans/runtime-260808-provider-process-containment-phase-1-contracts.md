---
title: "Provider Process Containment Phase 1 Execution Plan"
created: 2026-08-08
updated: 2026-08-08
tags: [runtime, provider, profile, contract, implementation]
---

# Phase Execution Plan

- Phase: `1 — Profile contract and approved baseline`
- Branch/base:
  `azents/runtime-containment-1-contracts` →
  `main`
- PR boundary: Add the approved snapshot and implementation plans, then introduce
  the portable Profile v2 containment contract without advertising or activating
  physical Provider containment.
- Inputs:
  - confirmed `runtime-260808/REQ`;
  - accepted `runtime-260808/ADR-D1` through `ADR-D10`;
  - approved `runtime-260808/DESIGN` revision 1 and authority IDs `M1` through
    `M12`;
  - current Runtime Profile Specs and implementation;
  - current Kubernetes and Docker Provider capability contract shapes.
- Deliverables:
  - tracked Requirements, ADR, approved Design, multi-phase plan, and this phase
    execution plan;
  - unchanged Profile schema version 1 behavior;
  - Profile schema version 2 for Kubernetes Pod and Docker Container families;
  - one shared portable process-containment module with no backend-specific
    arguments;
  - typed rejection of containment combined with DinD;
  - required capability derivation and Provider compatibility evaluation;
  - canonical effective-Profile serialization and digest coverage;
  - recreation classification for containment adoption/removal and v1/v2 change;
  - shared Runtime Control resolved-configuration parsing for all four Profile
    kind/version variants without Provider-side activation;
  - required API/OpenAPI/generated-client changes for the Profile contract;
  - no Provider capability advertisement, Runner bootstrap, or physical
    containment behavior.
- Non-goals:
  - Runner backend or bwrap implementation;
  - Provider resource, mount, security, or capability activation;
  - prompt, readiness, status, API presentation beyond the Profile contract;
  - frontend containment controls beyond generated contract compatibility;
  - E2E containment behavior;
  - living Spec promotion or implemented dates.
- Interfaces:
  - Profile v1 documents parse and canonicalize exactly as before.
  - Profile v2 uses the existing Kubernetes and Docker contract families.
  - The shared containment module expresses only portable required behavior.
  - Workspace policy cannot remove or weaken containment.
  - Compatibility requires `runtime.process-containment` only when the module is
    present.
  - Containment plus DinD fails typed validation before publication or resolution.
  - The shared Runtime Control envelope parser preserves typed v1 behavior and
    accepts canonical v2 Profiles for later Provider phases.
  - Provider registrations continue advertising only their current v1 support in
    this phase.
  - Any API schema change is source-generated through OpenAPI tooling.
- Approved Design mechanisms: `M1`, `M10`, `M11`
- Authority references:
  `runtime-260808/REQ-1`, `REQ-8`, `REQ-9`, `REQ-11`, `REQ-13`, `REQ-15`;
  `runtime-260808/ADR-D5`, `ADR-D9`;
  `runtime-260808/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations:
  Replace Profile-v1-only parsing, capability, and recreation assumptions while
  retaining version 1 as an unchanged supported contract.
- Absence verification:
  Static search finds no Profile parser or compatibility path that assumes schema
  version 1 is exhaustive; tests prove v1 compatibility and v2 explicit handling.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Snapshot and plans | `/root` | `docs/azents/{requirements,adr,design,plans}/runtime-260808-provider-process-containment*` | Approved snapshot | Tracked authority and execution scope | Snapshot validator, `git diff --check` |
| Core Profile contract | `/root` | `python/apps/azents/src/azents/core/runtime_profile.py`; focused tests | Fixed Profile v2 interface | Typed v1/v2 module, validation, capability, recreation behavior | Ruff, format, ty, focused pytest |
| Runtime Control Profile contract | `/root` | `python/libs/azents-runtime-control/src/azents_runtime_control/runtime_configuration.py`; focused tests | Core Profile contract | Typed resolved v1/v2 parsing with no Provider activation | Ruff, format, ty, focused pytest |
| Persistence and services | `/root` | `python/apps/azents/src/azents/{repos,rdb,services}/**/*runtime_profile*`; focused tests only where contract propagation requires change | Core contract | Canonical persisted/resolved v2 behavior without new state authority | Focused repository/service pytest |
| API and generated contracts | `/root` | affected Admin/Public API data/routes, OpenAPI specs, generated Python/TypeScript clients | Stable backend Profile schema | Source-generated Profile v2 wire contract | OpenAPI generation, client generation, type checks |
| Independent review | `/root/runtime-containment-reviewer` | Read-only complete phase diff | Stable implementation and validation | Requirements/security/compatibility/interface findings | Reviewer report or explicit no findings |

- Integration order:
  1. Commit the approved snapshot and tracked plans.
  2. Add the versioned core Profile module and exhaustive validation.
  3. Extend the shared Runtime Control resolved-configuration parser without
     changing either Provider's advertised or activated contract.
  4. Propagate the typed contract through persistence/service/API boundaries only
     where required.
  5. Regenerate OpenAPI and clients when their source contracts change.
  6. Run focused validation and the scope-drift check.
  7. Request independent review from `/root/runtime-containment-reviewer`, correct
     required findings, and rerun affected checks.
  8. Commit and open PR 1 before creating the phase 2 branch.
- Independent review:
  - Reviewer: `/root/runtime-containment-reviewer`.
  - Scope: complete phase 1 diff.
  - Criteria: v1 compatibility, explicit v2 semantics, no backend arguments,
    DinD exclusion, exact capability derivation, recreation correctness, no
    premature Provider advertisement, no new state authority, generated-contract
    integrity, and `Design delta: None`.
  - Inputs: Requirements, ADR, Design revision 1, multi-phase plan, this phase
    plan, diff, and validation results.
  - Output: grounded findings or explicit no findings.
- Final validation:
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run ty check --error-on-warning`
  - `cd python/libs/azents-runtime-control && uv run ruff format --check
    src tests && uv run ruff check src tests && uv run ty check
    --error-on-warning && uv run pytest`
  - focused Runtime Profile and affected API/repository pytest
  - OpenAPI dump and generated-client drift checks when affected
  - `cd typescript && pnpm run typecheck` when generated TypeScript changes
  - snapshot validation
  - `git diff --check`
- Scope-drift check:
  Confirm the diff implements only `M1`, the Profile-contract portion of `M10`,
  and recreation compatibility in `M11`. Remove Runner, Provider activation,
  prompt, readiness, new status persistence, UI behavior, or later-phase E2E.
- Context checkpoint:
  Record v1/v2 contract behavior, changed wire/generated interfaces, validation,
  reviewer result, removal absence evidence, branch/base/commit/PR, and the exact
  inputs required by phase 2.
