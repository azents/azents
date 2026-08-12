---
title: "Agent-Managed Dynamic Worktrees Phase 2 Execution Plan"
created: 2026-08-12
tags: [agent, engine, worker, mailbox, runtime, git, worktree]
---

# Agent-Managed Dynamic Worktrees Phase 2 Execution Plan

## Phase Execution Plan

- Phase: `2 — Dynamic creation`
- Branch/base: `feature/agent-worktrees-2-create` → `feature/agent-worktrees-1-bridge`
- PR boundary: eligible Dynamic Worktree Toolkit and durable Agent-requested worktree creation through the Phase 1 fresh-Run bridge
- Inputs: completed Phase 1 bridge contracts at `448720599`; confirmed `worktree-260812/REQ`; accepted `worktree-260812/ADR`; approved `worktree-260812/DESIGN` revision 2
- Deliverables: conditional `create_git_worktree` projection, exact current-context Project admission, idempotent bridge enqueue and wake dispatch, pinned create execution, selected-Project `HEAD` default or explicit ref/branch, linked-worktree source resolution, collision-safe generated branch/path, allocation and Project registration, Project Catalog and Skill `latest` refresh, and bounded terminal continuation
- Non-goals: `remove_git_worktree`, `agent_action` path claims, dirty/force handling, checkout removal, branch deletion or cleanup, deterministic E2E, Living Spec promotion, snapshot implementation dates
- Interfaces: always-resolved Dynamic Worktree Toolkit with conditional tool projection; `source_project_path`, optional `starting_ref`, and optional `branch_name` input; authoritative `ClientToolExecutionContext` call identity; Phase 1 `TurnActionBridgeBoundary`; existing mailbox, owner-activity, wake, Runner Git, allocation, Project Catalog, and Skill synchronization contracts
- Approved Design mechanisms: `M1`, `M2`, `M6`, `M8`, `M9`
- Authority references: `worktree-260812/REQ-1` through `REQ-4`; `worktree-260812/REQ-7`; `worktree-260812/ADR-D1`, `ADR-D2`, `ADR-D3`; approved Design revision 2 Agent-Facing Tools, Durable Bridge Admission, Creation Lifecycle, and AgentRun Handoff; current Toolkit, workspace, project-catalog, operation, and run-resume Specs
- Design delta: `None`
- Removal obligations: replace the Agent-facing need for manual Git/worktree commands during creation with the registered create bridge while preserving existing user-facing `create_git_worktree` TurnAction and ordinary Toolkit behavior
- Absence verification: static search and focused tests prove no removal tool is projected, no Git discovery or mutation occurs in the Toolkit handler, no Project is registered before confirmed Git success, and existing user-facing creation behavior remains independently reachable

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Dynamic Worktree Toolkit | `/root` | `azents/engine/tools/**`, focused Toolkit tests | Phase 1 boundary and authoritative tool context | conditional create tool, exact Project admission, stable acceptance result | schema, eligibility, admission, duplicate-call, and rejection tests |
| Worker composition and dispatch | `/root` | `azents/worker/deps.py`, `azents/worker/run/executor.py`, focused worker tests | Toolkit provider and Run-scoped boundary | always-resolved provider, per-Run binding, owner activity, durable wake | composition and fresh-Run integration tests |
| Agent creation execution | `/root` | `azents/services/session_git_worktree/**`, operation and repository collaborators | pinned action and existing create lifecycle | source revalidation, HEAD/ref/branch resolution, allocation, Runner mutation, Project registration | service success, failure, replay, linked-source, and drift tests |
| Project and Skill refresh | `/root` | existing Project Catalog and Skill synchronization integration points plus focused tests | confirmed created Project | refreshed Project Catalog and filesystem Skill `latest` before terminal handoff | catalog, Skill projection, and continuation evidence tests |
| Runtime integration | `/root` | existing typed Runner worktree operations and integration fakes/tests | authoritative Runtime workspace evidence | exact source anchor, target, branch, and starting commit execution | Runtime request and workspace-authority tests |

- Integration order: Toolkit schema and eligibility → exact Project admission and bridge enqueue → worker provider/boundary composition → pinned action execution → creation defaults and linked-source resolution → allocation/Project/catalog/Skill refresh → terminal continuation and fresh-Run integration
- Independent review: `hardtack` reviews the stable Phase 2 diff read-only against Requirements, ADR, approved Design revision 2 M1/M2/M6/M8/M9, this plan, Phase 1 interfaces, and current Specs; output is limited to authority gaps, security/data-loss, Git mutation safety, idempotency/fresh-Run failure, Project/Skill refresh failure, removal-obligation failure, or material scope drift
- Final validation: `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check --error-on-warning`, targeted Toolkit/service/worker/Runtime pytest, relevant broader backend pytest, `git diff --check`, and pre-commit hooks on the stable diff
- Scope-drift check: all approved Phase 2 creation behavior is covered; no removal projection or lifecycle, path-claim enum, direct branch deletion, compatibility fallback, fixed Workspace root, generic handoff authority, E2E/spec promotion, or unrelated Toolkit behavior is added
- Context checkpoint: Phase 2 ends with Agents able to durably request a managed worktree from an exact current Project and continue in a fresh Run with refreshed Project and Skill context; Phase 3 consumes the Toolkit and allocation authority to add branch-preserving removal

## Execution Checkpoint

- State: implementation, independent review, and final validation complete; stable diff awaiting commit and stacked PR creation
- Completed behavior: eligible Agents receive the dynamic creation tool; exact current-Project admission persists an idempotent bridge request; the worker executes pinned creation with Runner-reported repository authority, registers and catalogs the confirmed Project, refreshes Skill projection, and resumes through one bounded fresh-Run continuation
- Changed interfaces: `GitListRefsFinalSuccess.repository_anchor_path`; Runtime Runner and control-client repository-anchor propagation; Run-scoped Dynamic Worktree Toolkit binding
- Authority and drift: approved `M1`, `M2`, `M6`, `M8`, and `M9` creation scope is implemented with `Design delta: None`; static diff inspection found no Phase 3 removal lifecycle, branch deletion, force handling, E2E, or Spec-promotion scope
- Removal and absence evidence: no removal tool is projected; Toolkit admission performs no Git mutation; Project registration follows confirmed Runner success; existing user-facing worktree creation remains reachable
- Independent review:
  - initial `hardtack` review found that downstream Catalog or Skill failure could leave a generated Project registered, and that missing Skill dependencies could permit a successful continuation without refreshing `latest`
  - the correction now compensates generated Project, Catalog, and Skill state before failed or cancelled Agent-create terminalization; preserves failed allocation evidence for cleanup; and fails closed before Runner Git I/O when mandatory Skill dependencies are unavailable
  - targeted `hardtack` re-review found no remaining Critical or Warning findings
- Validation evidence:
  - generated Runtime Control protobuf artifacts regenerated successfully from the schema
  - backend full Ruff, format, and `ty`: passed
  - backend Phase 2 Toolkit, resolver, live projection, service, and executor tests: `145 passed`
  - related broader backend suite: `187 passed`
  - Runtime Runner full Ruff, format, and `ty`; focused operation tests: `59 passed`
  - Runtime Control full Ruff, format, and `ty`; focused client tests: `15 passed`
  - `git diff --check`: passed
- Remaining Phase 2 work: CI-equivalent repository pre-commit hooks, final stable-diff verification, commit, and stacked PR creation
- Remaining feature scope: Phase 3 branch-preserving removal; Phase 4 deterministic E2E, Living Spec promotion, snapshot implementation dates, and plan cleanup
