---
title: "Agent-Managed Dynamic Worktrees Phase 1 Execution Plan"
created: 2026-08-12
tags: [agent, engine, worker, mailbox, migration, worktree]
---

# Agent-Managed Dynamic Worktrees Phase 1 Execution Plan

## Phase Execution Plan

- Phase: `1 — Durable bridge foundation`
- Branch/base: `feature/agent-worktrees-1-bridge` → `main`
- PR boundary: internal durable TurnAction bridge and fresh-Run handoff, without model-visible worktree tools or new Git behavior
- Inputs: confirmed `worktree-260812/REQ`, accepted `worktree-260812/ADR`, approved `worktree-260812/DESIGN` revision 2
- Deliverables: internal bridge action and continuation persistence, predecessor fence, bridge terminal handoff, Run-scoped boundary latch, provider-independent boundary poll, operation `complete_run`, and recovery tests
- Non-goals: Agent-facing create/remove tools, create defaults, branch-preserving removal, `agent_action` path claims, E2E, Living Spec promotion, snapshot implementation dates
- Interfaces: closed bridge action types; hidden continuation payload with originating and predecessor Run IDs; Toolkit/Engine-only boundary object; `OperationActionProcessResult.complete_run`; continuation processor terminal predecessor gate
- Approved Design mechanisms: `M2`, `M3`, `M4`, `M5`, `M10`, `M11`
- Authority references: `worktree-260812/REQ-1`, `REQ-4`, `REQ-6`, `REQ-7`; `worktree-260812/ADR-D1`, `ADR-D2`; current mailbox, execution-loop, run-resume, conversation, workspace, and Toolkit Specs
- Design delta: `None`
- Removal obligations: split operation same-Run invalidation from bridge fresh-Run completion; prevent generic FunctionTool metadata handoff; exclude same-Run Skill reactivation
- Absence verification: static search and tests show no generic handoff metadata/flag, ordinary invalidation still preserves Toolkit/prompt state, and no new Skill reactivation lifecycle exists

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Persistence contracts | `/root` | `azents/core/enums.py`, `azents/engine/events/action_messages.py`, mailbox model/data/repository/service, event payload/lowering paths | current mailbox and event unions | bridge action types, continuation payload, hidden promotion, deterministic identity | payload/repository/service/migration tests |
| Migration | `/root` | `python/apps/azents/db-schemas/rdb/migrations/**`, `db-schemas/rdb/revision` | persistence enums | generated enum revision on current linear head | Alembic heads and migration integration |
| Atomic terminal handoff | `/root` | `azents/services/session_git_worktree/**`, action execution repositories | bridge payload | one terminal history plus one continuation and live-state removal | service replay and recovery tests |
| Engine boundary latch | `/root` | `azents/engine/events/execution.py`, `engine_adapter.py`, focused tests | client tool call identity and boundary poll | one post-tool poll for an admitted bridge regardless of provider follow-up | execution and adapter tests |
| Worker Run handoff | `/root` | `azents/worker/run/executor.py`, Session lifecycle/idle tests | Engine latch and operation result | immediate promotion-loop stop, predecessor terminalization, fresh later Run | worker/recovery/idle tests |

- Integration order: persistence union and migration → continuation processor → atomic terminalization → operation result propagation → Run-scoped latch → Engine post-tool polling → recovery and regression tests
- Independent review: `hardtack` reviews the stable Phase 1 diff read-only against Requirements, ADR, approved Design revision 2 M2/M3/M4/M5/M10/M11, this plan, and current Specs; output is limited to authority gaps, security/data-loss, migration safety, fresh-Run/exactly-once failure, removal failure, or material scope drift
- Final validation: `uv run ruff check`, `uv run ruff format --check`, `uv run pyright`, targeted mailbox/action/service/Engine/worker pytest, Alembic head/revision checks, and `git diff --check`
- Scope-drift check: all approved Phase 1 mechanisms are implemented; no Agent tool projection, create/remove Git behavior, compatibility reader, generic handoff authority, or same-Run Skill refresh is added
- Context checkpoint: Phase 1 ends with durable but model-unreachable bridge infrastructure; Phase 2 consumes the closed boundary to add creation
