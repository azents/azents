---
title: "Optional Managed Runtime Phase 8 Validation and Spec Promotion"
created: 2026-08-10
tags: [agent, runtime, workspace, testenv, e2e, documentation]
---
# Phase Execution Plan

- Phase: `8 — Validation and Spec Promotion`
- Branch/base: `azents/runtime-optional-capability-8-validation-specs` →
  `azents/runtime-optional-capability-7-web-ux`
- PR boundary: Prove the complete Optional Managed Runtime product contract through
  deterministic, focused Docker Runtime Provider, and real-browser Web Surface E2E;
  validate migration and rollout boundaries; promote current Living Specs; mark the
  approved snapshot implemented; and remove all temporary feature plans.
- Inputs: Completed Phase 1–7 implementation and public/Web contracts; confirmed
  `runtime-260803/REQ`; accepted `runtime-260803/ADR`; approved
  `runtime-260803/DESIGN` revision 3; current Living Specs and E2E lane policy.
- Deliverables:
  - Deterministic public API E2E proves Runtime-free Agent creation and model-only
    execution without physical Runtime creation, plus stable Runtime-free Session
    authority after a later Runtime add.
  - Focused Docker Runtime Provider E2E proves explicit add, lazy first physical use,
    temporary stop versus irreversible remove, Provider outage/reconnect convergence,
    exact removal completion, and higher-generation re-add without historical
    Workspace or Session binding revival.
  - Removal E2E proves every Team and private User Session tree is fenced while public
    impact/progress remains aggregate-only and content-free.
  - Web Surface E2E proves Runtime-free Agent settings and Workspace states, explicit
    Profile-backed addition, destructive confirmation, and removal progress through
    real server projections and generated-client actions.
  - Migration and rollout evidence proves existing Agents remain `managed`, omitted
    Profiles remain managed-unconfigured for migrated/current explicit managed state,
    old executors must drain before feature enablement, and rollback after new state
    activation is roll-forward.
  - Living Specs describe the implemented capability, transition, Session binding,
    removal, privacy, execution, Workspace, and E2E behavior.
  - Requirements and Design receive the same `implemented: 2026-08-10` marker only
    after validation and Spec promotion complete.
  - The implementation plan and all phase plans, including this file, are removed
    after their execution purpose is complete.
- Non-goals: New product behavior, API/schema/generated-client changes, new capability
  states, new removal stages, Kubernetes live evidence presented as Docker evidence,
  compatibility fallbacks, rollout against a live deployment, PR merge, or `main`
  updates.
- Interfaces:
  - E2E creates and mutates product state through public/admin APIs and the real Web
    UI only; it never writes directly to PostgreSQL.
  - Public E2E consumes the generated Python client add/remove/read/lifecycle models
    without editing generated files.
  - Web Surface E2E consumes the Phase 7 UI and server-computed Runtime actions; it
    does not introduce test-only frontend authority.
  - Docker Runtime Provider evidence uses the existing credential-free fixture and
    current Provider reconnect controls.
  - Current Specs, Requirements, ADR, and approved Design remain the only product and
    design authority; this plan only decomposes validation and promotion work.
- Approved Design mechanisms: `M10`, `M12`, and validation of implemented `M1`–`M15`.
- Authority references: `runtime-260803/REQ-1` through `REQ-10`;
  `runtime-260803/ADR-D1` through `ADR-D6`; approved Design revision 3;
  `test-strategy-e2e-primary`; current Agent, conversation, Toolkit, Workspace,
  execution-loop, Runtime control, Runtime persistence, file exchange, and resume
  Specs.
- Design delta: `None`
- Removal obligations:
  - Replace remaining pre-feature E2E assumptions that every created Agent owns a
    Runtime with explicit Runtime-free or managed fixture intent.
  - Replace stale Living Spec statements that require a Runtime row, infer missing
    Runtime as not-started, or omit irreversible capability removal and Session
    binding invalidation.
  - Remove the Optional Managed Runtime implementation plan and all eight phase plans
    after validation, Spec promotion, and implemented markers are complete.
- Absence verification:
  - Repository searches find no E2E fixture relying on implicit Workspace-default
    Runtime capability for a scenario that requires managed execution.
  - Public and Web removal evidence contains no private Session title, owner, path,
    content, actor, idempotency key, cursor, lease, or internal authority identifier.
  - Current Specs contain no mandatory Runtime identity for model-only execution, no
    absent-Runtime-to-`NOT_STARTED` inference, and no reversible removal path.
  - No `runtime-260803-optional-managed-runtime-*-plan.md` or implementation plan
    remains after cleanup.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Deterministic and focused Runtime E2E | `root` | `testenv/azents/e2e/src/tests/azents/public/test_runtime_optional_capability.py`, focused existing Runtime E2E helpers when required | Phase 6 public contracts, Phase 5 coordinator, Docker Provider fixture | Runtime-free, add/lazy start, remove/outage/reconnect, privacy, and re-add journeys | Focused deterministic and `runtime_provider` pytest, Ruff, `ty` |
| Web Surface Runtime E2E | `root` | `testenv/azents/e2e/src/tests/azents/public/test_runtime_capability_web.py` | Phase 7 Web UX and real-server browser fixture | Settings and Workspace capability/add/removal browser journey | Focused `web_surface` pytest, browser failure artifacts |
| Migration, rollout, and absence validation | `root` | Existing migration/unit/E2E tests and repository searches; no product source ownership unless a verified defect is found | Phases 1–7 | Existing-Agent managed backfill, rollout boundary, and removed-authority evidence | Migration pytest, deterministic lane, exact searches |
| Living Spec promotion | `root` | Impacted `docs/azents/spec/{domain,flow}/*.md` selected by complete-stack `/spec-review` | Stable validated implementation | Current behavior, permissions, failures, privacy, and E2E policy | `/spec-review`, docs snapshot validation, pre-commit |
| Snapshot markers and plan cleanup | `root` | `docs/azents/{requirements,design}/runtime-260803-optional-managed-runtime.md`, `docs/azents/plans/runtime-260803-optional-managed-runtime-*.md` | Validation and Spec promotion complete | Immutable implemented snapshot and removal of temporary plans | Frontmatter/snapshot validation, absence search |

- Integration order: tracked Phase 8 plan → deterministic public API E2E → focused
  Docker Runtime lifecycle/removal/re-add E2E → Web Surface E2E → migration and
  absence validation → complete-stack spec review and Living Spec promotion →
  implemented markers → plan cleanup → final integrated validation.
- Independent review: `hardtack` reviews the complete Phase 8 diff against M10/M12
  and the M1–M15 E2E matrix, focusing on product-path state creation, Docker evidence
  labeling, private User Session boundaries, exact removal/re-add convergence, Spec
  completeness, immutable snapshot markers, and full plan cleanup. Security, privacy,
  data-loss, migration, or material interface corrections require targeted re-review
  by the same reviewer.
- Final validation:
  - Focused new deterministic E2E.
  - Focused new Docker Runtime Provider E2E.
  - Focused new Web Surface E2E.
  - Required deterministic, Runtime Provider, and Web Surface CI aggregate gates.
  - Existing migration tests and complete backend/public-client tests affected by
    corrections.
  - `uv run ruff check .`, `uv run ruff format --check .`, and
    `uv run ty check --error-on-warning` in `testenv/azents/e2e`.
  - Complete-stack `/spec-review`, docs snapshot validation, repository pre-commit,
    `git diff --check`, and exact absence/privacy searches.
- Scope-drift check: Every E2E assertion and Spec statement must map to confirmed
  Requirements, accepted ADRs, M1–M15, or unchanged current Specs. The phase adds no
  product state, authority, fallback, mutation, rollout action, or compatibility
  behavior. Verified implementation defects are fixed in their owning earlier phase
  and dependent branches are rebased before Phase 8 continues.
- Context checkpoint: Phases 1–7 provide optional persistence, Runtime-free
  execution, Session binding authority, explicit transitions, durable removal,
  public/generated contracts, and capability-aware Web UX. Phase 8 owns only product
  verification, rollout evidence, current-Spec promotion, implemented markers, and
  temporary plan cleanup. Required fixtures are credential-free; Kubernetes live
  evidence remains optional and is not required for the Docker-backed completion
  boundary.
