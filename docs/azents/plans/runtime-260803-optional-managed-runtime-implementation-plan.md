---
title: "Optional Managed Runtime Implementation Plan"
created: 2026-08-10
tags: [agent, runtime, workspace, backend, frontend, migration, testenv]
---
# Optional Managed Runtime Implementation Plan

## Authority and Scope

- Requirements: [runtime-260803/REQ](../requirements/runtime-260803-optional-managed-runtime.md)
- ADR: [runtime-260803/ADR](../adr/runtime-260803-optional-managed-runtime.md)
- Approved Design: [runtime-260803/DESIGN](../design/runtime-260803-optional-managed-runtime.md)
- Approved Design revision: `3`
- Approved mechanisms: `M1` through `M15`
- Design delta: `None`

## Objective

Make managed Runtime an optional Agent-scoped capability. New Agents default to
Runtime-free execution, existing Agents retain managed capability, administrators
can add a lazily provisioned Runtime, and irreversible removal deletes Runtime-owned
state only after exact physical-deletion acknowledgement while preserving retained
Agent and Session state.

## Delivery Stack

All branches are sequential. Every PR is opened before the stack waits on CI.

| Phase | Branch | Base | Deliverable | Mechanisms |
| --- | --- | --- | --- | --- |
| 1 | `azents/runtime-optional-capability-1-foundation` | `main` | Additive persistence foundation, backfills, repository contracts, and approved snapshot documents | M1, M2, M11, M13 |
| 2 | `azents/runtime-optional-capability-2-runtime-free-core` | Phase 1 | Server capability catalog, Runtime-free Agent/Session admission, optional Runtime execution identity, and capability-filtered engine/toolkit projection | M1, M4, M8, M9, M15 |
| 3 | `azents/runtime-optional-capability-3-session-bindings` | Phase 2 | Session binding lifecycle and Runtime-dependent Workspace, Project, Git, Skill, transfer, credential, and archive-cleanup fencing | M4, M7, M13, M15 |
| 4 | `azents/runtime-optional-capability-4-runtime-transitions` | Phase 3 | Dedicated add/rearm domain transitions, Profile source CAS, terminal acknowledgement kinds, and Provider reconnect-safe deletion dispatch | M3, M8, M9, M11, M15 |
| 5 | `azents/runtime-optional-capability-5-removal` | Phase 4 | Durable irreversible removal coordinator, Agent-wide work interruption, privacy-safe impact, product cleanup, and finalization | M2, M7, M9, M11, M14, M15 |
| 6 | `azents/runtime-optional-capability-6-public-contracts` | Phase 5 | Unified public Runtime read model, add/remove actions, Agent projections, OpenAPI, and generated clients | M1, M5, M6, M14 |
| 7 | `azents/runtime-optional-capability-7-web` | Phase 6 | Runtime-free creation/settings guidance, Workspace empty/removal states, destructive confirmation, and contextual add flow | M5, M6, M14 |
| 8 | `azents/runtime-optional-capability-8-validation-specs` | Phase 7 | Required E2E matrix, rollout validation, living-spec promotion, implemented snapshot markers, and plan cleanup | M10, M12 and all implemented mechanisms |

## Fixed Interfaces and Boundaries

- Agent capability states are `none`, `managed`, and `removing`.
- `runtime_profile_id = null` remains managed-unconfigured when capability is
  `managed`; it never infers Runtime-free state.
- Generic Agent patch cannot add or remove Runtime capability.
- AgentRuntime remains one stable logical identity per Agent.
- Re-add uses the same logical Runtime only after exact terminal acknowledgement
  and advances desired generation.
- Runtime-free model and compatible remote work do not create AgentRuntime.
- Agent Workspace paths come only from current-generation Runner evidence.
- Session folder binding authority is independent of archive cleanup status.
- Invalidated and Runtime-free Session contexts never bind after a later Runtime add.
- Final removal confirmation is irreversible and PostgreSQL is the correctness
  authority; Redis is optional wake-up coordination.
- Team and private User Session trees are both fenced, but public removal impact is
  content-free aggregate evidence.
- Old workers, schedulers, and APIs are drained before new capability states are
  enabled. Rollback after state activation is roll-forward.
- No backward-compatibility fallback or legacy dual authority is introduced.

## Removal Obligations

| Existing authority or behavior | Owning phase | Replacement and absence evidence |
| --- | --- | --- |
| New-Agent Workspace-default Runtime selection | Phase 2 | Runtime-free default; creation tests prove no Runtime row or reconcile work |
| Input admission always ensuring AgentRuntime | Phase 2 | Optional Runtime identity; model-only tests and repository absence assertions |
| `shell_enabled` as complete Runtime authority | Phases 2–3 | Shared capability catalog; declaration inventory and stale-call rejection |
| Mandatory non-null Session folder path | Phases 1 and 3 | Nullable binding lifecycle; migration and path-authority tests |
| Stored path as setup/browser/archive/worktree authority | Phase 3 | Active binding plus capability/version and current Runner evidence |
| Missing AgentRuntime rendered as `NOT_STARTED` | Phase 6 | Unified Agent/removal/physical Runtime read model |
| Generic Profile patch granting capability | Phases 4 and 6 | Dedicated add/remove actions and managed-only Profile patch |
| Terminal delete as logical dead end | Phase 4 | Exact-acknowledgement higher-generation rearm |
| Runtime-owned Session/Agent Project and worktree state after removal | Phase 5 | Bounded cleanup and zero-retained-state verification |
| Runtime-only Skill, instruction, action, and credential projection after removal | Phases 3 and 5 | Capability-tagged cleanup and re-add absence tests |
| Pre-feature clients, fixtures, and tests assuming every Agent has Runtime | Phases 6–8 | Generated clients, explicit fixtures, repository search, E2E matrix |
| Stale Living Specs | Phase 8 | Spec promotion and spec-review evidence |

## Integration and Rollout

1. Phase 1 is additive and keeps current behavior.
2. Phases 2–5 implement backend behavior behind explicit capability states while
   rollout remains disabled.
3. Phase 6 publishes the complete public contract and generated clients.
4. Phase 7 consumes only server-computed state and actions.
5. Phase 8 proves migration, deterministic, focused Runtime Provider, and Web
   Surface behavior before promoting Specs and enabling rollout.

No phase enables a partially implemented Runtime-free or removing state in
production. Feature enablement belongs to the final validated boundary.

## Validation Matrix

| Area | Required evidence |
| --- | --- |
| Persistence | Alembic upgrade/downgrade tests, enum/constraint tests, existing-Agent and context backfill evidence |
| Capability and execution | Agent/input/Worker/Engine tests proving optional Runtime identity and capability-filtered projection |
| Session resources | Folder, Project browser, worktree, archive, Skill, transfer, and credential stale-authority tests |
| Runtime transitions | Repository/service/Control tests for add, source CAS, terminal acknowledgement, rearm, stale reports, and reconnect |
| Removal | Lease/idempotency, all-Session-tree interruption, privacy, cleanup cursors, Redis absence, and finalization tests |
| Public contracts | API contract tests, OpenAPI generation, Python/TypeScript generated-client compilation |
| Web | Component/story coverage and Web Surface E2E for creation, settings, Workspace, and destructive progress |
| Product E2E | Deterministic model-only, focused Docker Runtime lifecycle, Provider outage/reconnect, removal/re-add, User Session privacy |
| Quality | Ruff, format, ty, pytest, TypeScript format/lint/typecheck/build, spec review |

## Review and Context Checkpoints

- Independent reviewer for every phase: `hardtack`.
- Each phase includes a tracked execution plan, focused validation, scope-drift
  check, and context checkpoint.
- Every PR requests `hardtack` as reviewer.
- A material Design delta returns to feature-design before implementation proceeds.
- The full stack is created before CI monitoring begins.
- CI corrections are applied to the owning phase, then dependent branches are
  rebased and retargeted through the stacked-PR workflow.

## Completion

The feature is complete only when all eight PRs exist, every required check across
the stack passes, spec promotion is complete, Requirements and Design carry the
same implemented date, temporary plans are removed, and no Design-required removal
obligation remains.
