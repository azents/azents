---
title: "Agent-Managed Dynamic Worktrees Implementation Plan"
created: 2026-08-12
tags: [agent, engine, worker, mailbox, runtime, git, worktree, testenv]
---

# Agent-Managed Dynamic Worktrees Implementation Plan

- Requirements: [`worktree-260812/REQ`](../requirements/worktree-260812-agent-managed-dynamic-worktrees.md)
- Decisions: [`worktree-260812/ADR`](../adr/worktree-260812-agent-managed-dynamic-worktrees.md)
- Approved Design: [`worktree-260812/DESIGN`](../design/worktree-260812-agent-managed-dynamic-worktrees.md)
- Approved Design revision: `2`
- Approved mechanism IDs: `M1` through `M11`
- Design delta: `None`
- Implementation owner: Primary agent (`/root`)
- Independent reviewer: `hardtack`

## Delivery Shape

The feature ships as four stacked PRs. Each phase is committed and opened before the
next branch starts. All four PRs are created before stack-wide CI monitoring.

| Phase | Branch | Base | PR title | Approved mechanisms | Primary boundary |
| --- | --- | --- | --- | --- | --- |
| 1 | `feature/agent-worktrees-1-bridge` | `main` | `Agent-managed worktrees [1/4]: Add durable Run handoff` | `M2`, `M3`, `M4`, `M5`, `M10`, `M11` | internal action and continuation persistence, predecessor fence, bridge latch, provider-independent boundary poll, fresh-Run recovery |
| 2 | `feature/agent-worktrees-2-create` | Phase 1 | `Agent-managed worktrees [2/4]: Add dynamic creation` | `M1`, `M2`, `M6`, `M8`, `M9` | eligible Agent Toolkit, exact Project authority, create lifecycle, Project/catalog/Skill refresh |
| 3 | `feature/agent-worktrees-3-remove` | Phase 2 | `Agent-managed worktrees [3/4]: Add branch-preserving removal` | `M1`, `M2`, `M7`, `M8`, `M9` | exact allocation authority, path claims, dirty/force handling, checkout and Project removal with branch preservation |
| 4 | `feature/agent-worktrees-4-validation` | Phase 3 | `Agent-managed worktrees [4/4]: Validate and document lifecycle` | full `M1`–`M11` validation | deterministic E2E, External Channel continuity, migration verification, Living Specs, snapshot implementation dates, plan cleanup |

## Fixed Interfaces and Integration Boundaries

- PostgreSQL mailbox, ActionExecution, Event, allocation, Project, and AgentRun state
  remains the only correctness authority. Redis and WebSocket remain routing and
  projection aids.
- Only the registered Dynamic Worktree Toolkit receives the Run-scoped
  `TurnActionBridgeBoundary`; the Engine execution request receives the same object.
  Function-tool arguments, outputs, metadata, hooks, and generic Toolkit context cannot
  request Run handoff.
- Bridge admission uses the authoritative `ClientToolExecutionContext` call identity and
  commits an idempotent `action_message` before marking the Run boundary.
- Only `agent_create_git_worktree` and `agent_remove_git_worktree` operation results may
  set `complete_run`. Ordinary `context_invalidated` actions retain same-Run Toolkit and
  prompt reuse.
- Bridge terminalization atomically appends one `action_execution_result`, enqueues one
  hidden `turn_action_continuation`, and removes live action state.
- The continuation stores the Run that terminalized the action as
  `predecessor_run_id`. Its processor leaves the FIFO row pending while that Run is
  nonterminal and atomically appends one deterministic `system_reminder` plus deletes the
  row after the predecessor is terminal.
- A pending `WAKE_SESSION` bridge continuation blocks Goal and External Channel idle
  continuation generation through the existing true-idle fence.
- Creation accepts a registered current-context Project path and pins its Project
  identity. Removal accepts a current-context managed-worktree path and pins its
  allocation and linked Project identity.
- Git and path authority is revalidated from current Runner-reported Workspace evidence
  immediately before side effects.
- Agent removal never deletes the preserved branch. Existing archive and manual cleanup
  behavior remains unchanged.

## Phase Dependencies and Context Checkpoints

### Phase 1 — Durable bridge foundation

Inputs: approved Design revision 2 and existing mailbox, operation, Engine, Run, Skill,
and broker lifecycles.

Outputs:

- internal bridge action schemas and hidden continuation payload;
- generated enum migration and revision alignment;
- predecessor-aware continuation promotion and hidden system-reminder lowering;
- atomic bridge terminal history and continuation handoff;
- Run-scoped bridge latch and post-tool input polling for both provider follow-up modes;
- operation `complete_run` propagation and immediate FIFO-loop stop;
- fresh-Run and recovery tests, while retaining ordinary same-Run invalidation; and
- no public Agent tool projection or Git behavior yet.

Checkpoint to Phase 2: bridge infrastructure is durable and testable, but unreachable
from model-visible tools.

### Phase 2 — Dynamic creation

Inputs: Phase 1 bridge contracts.

Outputs:

- eligible Dynamic Worktree Toolkit with `create_git_worktree`;
- exact current-context Project admission and stable call idempotency;
- owner activity plus durable wake dispatch;
- pinned Project create action execution;
- default selected-Project `HEAD`, optional explicit ref/branch, linked-worktree source,
  collision-safe generated branch/path;
- allocation, Project, catalog, and Skill `latest` refresh before terminal handoff; and
- focused Toolkit, service, worker, Skill, and Runtime integration evidence.

Checkpoint to Phase 3: Agents can create managed worktree Projects and continue in a
fresh Run with refreshed context.

### Phase 3 — Branch-preserving removal

Inputs: Phase 2 Toolkit and shared bridge.

Outputs:

- `remove_git_worktree` projection in the same Toolkit;
- exact current-context allocation and linked Project admission;
- `agent_action` path claims and generated enum migration;
- non-force dirty refusal, explicit force discard, ambiguous outcome preservation;
- checkout, Project, catalog, and Skill projection removal;
- branch preservation and archive-cleanup skip behavior; and
- absence evidence proving Agent removal never calls branch deletion.

Checkpoint to Phase 4: complete product lifecycle exists with deterministic lower-level
coverage.

### Phase 4 — Validation, Specs, and cleanup

Inputs: stable Phase 3 behavior and fresh deterministic Runtime/test prerequisites.

Outputs:

- deterministic Web and External Channel E2E for creation, removal, both follow-up
  modes, crash/reconnect, duplicate admission, Project/Skill visibility, and branch
  preservation;
- full migration, backend, TypeScript/generated-contract, and Runtime validation;
- authority, removal, and absence audit against `M1`–`M11`;
- updates to `agent-execution-loop.md`, `run-resume.md`, `workspace.md`, and other
  affected Living Specs;
- matching `implemented: 2026-08-12` dates on Requirements and Design after validation;
  and
- deletion of this plan and every phase plan after spec promotion.

Checkpoint: every stacked PR exists, all required CI is green, and no PR is merged
without separate requester approval.

## Workstream Ownership

| Workstream | Owner | Primary paths | Interfaces produced/consumed |
| --- | --- | --- | --- |
| Bridge persistence and migration | `/root` | `azents/core/enums.py`, action schemas, mailbox payload/model/repository/service, Alembic revisions | bridge action types, continuation payload, atomic promotion |
| Engine and worker Run handoff | `/root` | `azents/engine/events/**`, `azents/worker/run/**`, Session lifecycle tests | boundary latch, `complete_run`, predecessor terminal fence |
| Dynamic worktree Toolkit | `/root` | `azents/engine/tools/**`, worker Toolkit composition | create/remove Agent tools and exact admission |
| Worktree create/remove service | `/root` | `azents/services/session_git_worktree/**`, worktree repositories and claims | pinned identity execution, Project/catalog/Skill mutation |
| Runtime and testenv validation | `/root` | Runner control clients/tests, `testenv/azents/**` | deterministic Git fixtures and E2E evidence |
| Independent review | `hardtack` | read-only across each phase diff | Requirements/Design/security/data-loss/migration/scope review |

## Removal Obligations

| Removal | Owning phase | Replacement | Absence verification |
| --- | --- | --- | --- |
| assumption that every Project-mutating action uses same-Run rebuild | 1 and 4 | ordinary invalidation remains same-Run; registered bridge actions use fresh-Run handoff | focused worker tests and qualified Living Spec language |
| tests treating `context_invalidated` as the only operation outcome | 1 | split `context_invalidated` and `complete_run` contracts | test search and explicit cases |
| generic tool result or metadata handoff proposal | 1 | closed boundary object shared only by registered Toolkit and Engine | type/search assertion for no generic metadata flag |
| direct same-Run Skill reactivation proposal | 1 and 2 | fresh Run `on_run_start` adopts `latest` | no new Skill reactivation hook; lifecycle tests |
| arbitrary path-only execution authority | 2 and 3 | admission-pinned Project/allocation identity plus execution revalidation | drift tests fail without side effects |
| branch-deleting cleanup reuse for Agent removal | 3 | dedicated branch-preserving removal using shared claims and Runner remove | no `delete_git_branch` call in Agent path; archive behavior remains tested |
| temporary plans | 4 | approved Design and promoted Living Specs | final tree absence check |

## Validation Matrix

- Phase-focused backend checks: Ruff, formatter, Pyright, and targeted pytest modules.
- Migration checks: Alembic-generated revisions, one linear head, revision-file
  alignment, mailbox migration integration, and upgrade validation.
- Engine checks: tool batch behavior through all supported adapters/lowerers,
  `needs_follow_up=true/false`, ordinary same-Run invalidation, bridge fresh-Run
  completion, predecessor crash fence, and exactly-once replay.
- Worktree checks: registered Project/allocation authority, default and explicit refs,
  linked sources, dirty/force removal, ambiguous outcomes, Project/catalog/Skill updates,
  and branch preservation.
- E2E: deterministic model and local Runtime fixtures; optional live provider variants
  may skip only for missing credentials.
- Final checks: complete Azents Python quality suite, affected TypeScript quality suite,
  required testenv/E2E lanes, documentation validation, spec review, and all stacked PR
  GitHub checks.

## Prerequisites and Blockers

- PostgreSQL is required for migration, mailbox, Run, and exactly-once integration tests.
- A managed local Runtime Runner and disposable Git repositories are required for
  deterministic worktree E2E.
- Redis may be present for routing tests but cannot be required for correctness.
- No live Slack, Discord, or model-provider credential is required for mandatory
  deterministic evidence.
- Any new product behavior, durable authority, compatibility fallback, lifecycle mode,
  or source of truth returns to feature design. Local implementation refinements remain
  `Design delta: None`.

## Review and Stack Policy

The exact independent reviewer and GitHub reviewer for every phase is `hardtack`.
Review inputs are the confirmed Requirements, accepted ADR, approved Design revision 2,
current Specs, phase execution plan, and phase diff. Review priority is
Requirements/Design authority, security and destructive authority, data loss, migration
safety, fresh-Run and exactly-once correctness, compatibility fallback, removal
obligations, and scope drift.

Each phase is committed and opened as a PR before the next phase starts. All four PRs
are created before CI monitoring. Dependent branches are rebased with the stacked-PR
workflow when an earlier phase changes. PRs are never merged without explicit requester
approval.
