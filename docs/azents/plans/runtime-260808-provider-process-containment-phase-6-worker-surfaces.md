---
title: "Provider-Owned Runtime Process Containment Phase 6 Worker Surfaces Plan"
created: 2026-08-09
updated: 2026-08-09
tags: [runtime, worker, prompt, readiness, api, frontend, implementation]
---

# Provider-Owned Runtime Process Containment Phase 6 Worker Surfaces Plan

## Phase Execution Plan

- Phase: `6 — Worker prompt, readiness, status, API, and Web surfaces`
- Branch/base:
  `azents/runtime-containment-6-worker-surfaces` →
  `azents/runtime-containment-5-kubernetes-provider`
- PR boundary: Desired-Profile Runtime guidance, one bounded matching-Runtime
  operation resolver, derived containment projections, generated clients, and
  Admin/Workspace Web consumption.
- Inputs: Completed Profile v2 contracts, Runner containment backend and operations,
  and Docker/Kubernetes Provider preparation from phases 1 through 5.
- Deliverables:
  - an immediate resolved desired-Profile behavior projection used by the Runtime
    static prompt without Runner requests or readiness waits;
  - one shared bounded explicit-operation resolver that accepts matching qualified
    `READY` or `BUSY` Runners and returns immutable generation/revision/Workspace
    evidence;
  - derived capability, adoption/recreation, nested-Docker, availability, and
    bounded-reason projections from existing authoritative state;
  - Admin Infrastructure Profile, Workspace Runtime Profile, Agent Runtime API, and
    Web presentation updates with regenerated clients.
- Non-goals:
  - Provider or Runner containment implementation changes;
  - a persisted containment boolean, lifecycle enum, qualification table, or
    migration;
  - backend arguments, mandatory-access-control rules, credentials, endpoints, or
    sensitive path inventories in prompt/API/UI;
  - prompt-time Runtime start, polling, Runner request, or readiness gating;
  - Phase 7 full-stack evidence, Living Spec promotion, implemented snapshot dates,
    or plan cleanup.
- Interfaces:
  - typed Profile v1/v2 and portable containment module from phase 1;
  - immutable desired configuration revision and existing applied revision,
    Runner generation/state, Workspace evidence, and lifecycle authority;
  - existing exact-generation Runner operation requests and cancellation/timeouts;
  - source-generated OpenAPI, Python clients, and TypeScript clients.
- Approved Design mechanisms: `M8`, `M9`, `M10`.
- Authority references:
  - `runtime-260808/REQ-13`, `REQ-15`, `REQ-16`;
  - `runtime-260808/ADR-D1`, `ADR-D2`, `ADR-D9`;
  - `runtime-260808/DESIGN` revision 2, especially Prompt Construction,
    Runtime-Dependent Readiness, Derived Product Projections, and API/Client/
    Frontend Impact.
- Design delta: `None`
- Removal obligations:
  - instantaneous TurnAction `runner_state == READY` failure;
  - caller-specific literal-`READY` checks and duplicated readiness polling for
    explicit Runtime operations;
  - Runtime prompt without typed desired-Profile behavior;
  - any containment-specific persisted status proposal.
- Absence verification:
  - repository searches show explicit operation call sites use the shared resolver
    and do not own polling loops or literal-`READY` qualification rules;
  - prompt tests prove no Runtime start, Runner request, or readiness call occurs;
  - schema/migration searches show no containment status column or lifecycle enum;
  - response tests prove projections are derived from desired Profile,
    desired/applied revision equality, and current Runner authority.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Desired Profile projection and prompt | `/root` | Runtime Profile repositories/resolution services, `engine/tools/builtin.py`, Worker prompt bindings and focused tests | Phase 1 typed Profile contracts | Code-owned contained/uncontained/blocked Runtime behavior fragments with no readiness dependency | Prompt snapshots, DB-only/no-readiness assertions, focused pytest |
| Shared operation target resolver | `/root` | Agent Runtime service/repository data, Runtime tools, file/workspace services, project/worktree TurnActions, directory validation, transfer target resolution and tests | Existing lifecycle requests, desired/applied revisions, Runner generation and Workspace evidence | Bounded cancellable immutable operation target accepting matching qualified `READY`/`BUSY` | Slow-start, timeout, cancellation, superseded revision/generation, BUSY, and call-site tests |
| Derived server projections | `/root` | Runtime Profile compatibility/workspace/admin services, Agent Runtime service, public/admin response models and tests | Desired Profile plus existing physical authority | Safe Admin and Workspace/Agent containment capability, adoption, recreation, availability, nested-Docker, and reason fields | Projection matrix, API route/data tests, migration/schema absence search |
| Generated contracts | `/root` | OpenAPI specs and generated Python/TypeScript public/admin clients | Stable source response schemas | Synchronized generated contracts without manual client edits | OpenAPI dump, client generation, generated drift and type checks |
| Admin and Workspace Web | `/root` | Admin Runtime Provider/Profile components, Workspace Runtime Profiles, Agent settings, Runtime status/workspace panel, tRPC adapters, stories, localized messages and tests | Generated TypeScript clients and server projections | Server-projection-only containment configuration/status presentation with bounded copy | TypeScript format, lint, typecheck, build, presentation tests, meaningful stories |

- Integration order:
  1. Add the desired-Profile projection and bounded prompt renderer.
  2. Introduce the shared operation target type/resolver and migrate explicit
     operation callers without changing operation envelopes.
  3. Add derived server projection types and API response fields.
  4. Regenerate OpenAPI and both Python/TypeScript client families.
  5. Update Admin and Workspace/Agent Web consumers and stories.
  6. Run absence searches, focused integration checks, and complete phase quality
     validation.
- Independent review:
  `/root/runtime-containment-reviewer` performs a read-only review against
  `runtime-260808/REQ-13/15/16`, `ADR-D1/D2/D9`, Design `M8/M9/M10`, this phase
  contract, and the final diff. Review priorities are prompt/readiness separation,
  exact revision/generation fencing, cancellation/timeout behavior, derived-state
  correctness, absence of persisted status or raw backend detail, API/client
  synchronization, and frontend non-recomputation.
- Final validation:
  - backend Ruff, format, `ty --error-on-warning`, and focused/full pytest;
  - OpenAPI dump and repository client generation commands;
  - generated Python client checks;
  - TypeScript format, lint, typecheck, build, and focused presentation tests;
  - prompt no-readiness and explicit-operation wait product tests;
  - schema/migration and caller-specific readiness absence searches;
  - `git diff --check` and pre-commit hooks.
- Scope-drift check:
  confirm complete `M8`, `M9`, and `M10` coverage; remove Provider/Runner changes,
  persisted containment authority, prompt-time physical-state dependencies,
  backend-specific product fields, automatic operation retry, Phase 7 Specs/E2E,
  or any material mechanism absent from approved Design Authority.
- Context checkpoint:
  phases 1 through 5 provide the typed desired Profile and physically qualified
  Provider/Runner evidence. Phase 6 changes only Worker consumption and derived
  product surfaces. The main risks are hidden readiness coupling, accepting a stale
  ready Runtime, duplicating availability logic in callers/frontends, exposing
  diagnostics too broadly, and generated-client drift. Phase 7 remains responsible
  for complete cross-Provider product E2E, authority/removal audit, Spec promotion,
  implemented dates, and plan cleanup.
