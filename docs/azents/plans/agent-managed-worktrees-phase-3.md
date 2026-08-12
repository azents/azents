---
title: "Agent-Managed Dynamic Worktrees Phase 3 Execution Plan"
created: 2026-08-12
tags: [agent, engine, worker, mailbox, runtime, git, worktree, removal]
---

# Agent-Managed Dynamic Worktrees Phase 3 Execution Plan

## Phase Execution Plan

- Phase: `3 — Branch-preserving removal`
- Branch/base: `feature/agent-worktrees-3-remove` → `feature/agent-worktrees-2-create`
- PR boundary: eligible Dynamic Worktree Toolkit removal and durable Agent-requested branch-preserving removal through the existing fresh-Run bridge
- Inputs: completed Phase 2 creation contracts at `057a53b58`; confirmed `worktree-260812/REQ`; accepted `worktree-260812/ADR`; approved `worktree-260812/DESIGN` revision 2
- Deliverables: conditional `remove_git_worktree` projection, exact current-context managed-allocation admission, idempotent bridge enqueue and wake dispatch, pinned removal execution, `agent_action` path claims, Runner inspection, non-force dirty refusal, explicit force discard, branch-preserving checkout removal, Project and Catalog deletion, Skill `latest` invalidation, cleaned allocation evidence, bounded retry or success continuation, and archive-cleanup skip behavior
- Non-goals: branch deletion, arbitrary Project removal, primary or unmanaged worktree removal, cross-Session removal, archive/manual cleanup behavior changes, deterministic E2E, Living Spec promotion, snapshot implementation dates, and plan cleanup
- Interfaces: the existing always-resolved Dynamic Worktree Toolkit and Run-scoped bridge boundary; `worktree_project_path` plus optional `force` input; authoritative `ClientToolExecutionContext` call identity; pinned `AgentRemoveGitWorktreeAction`; current allocation, Project, Runtime Workspace, path-claim, Runner inspect/remove, Catalog, Skill, terminal-history, and continuation contracts
- Approved Design mechanisms: `M1`, `M2`, `M7`, `M8`, `M9`
- Authority references: `worktree-260812/REQ-1`; `worktree-260812/REQ-5` through `REQ-7`; `worktree-260812/ADR-D1`, `ADR-D2`, `ADR-D3`; approved Design revision 2 Agent-Facing Tools, TurnAction Promotion and Execution, Branch-Preserving Removal Lifecycle, Failure and Recovery, Security and Permissions, and Removal and Replacement; current Toolkit, workspace, project-catalog, operation, cleanup, and run-resume Specs
- Design delta: `None`
- Removal obligations: replace Agent-facing reuse of archive/manual cleanup and its branch-deletion authority with a dedicated removal path that reuses only exact allocation authority, path claims, Runner inspection, and checkout removal while preserving the branch; preserve archive and manual cleanup behavior independently
- Absence verification: static search and focused tests prove Agent removal never invokes `delete_git_branch`, never accepts an ordinary Project or arbitrary path, never removes a Project before confirmed checkout removal, leaves dirty non-force and ambiguous outcomes registered, and leaves archive cleanup branch deletion behavior unchanged

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Dynamic Worktree removal tool | `/root` | `azents/engine/tools/dynamic_worktree.py` and focused tests | Phase 2 Toolkit and bridge | conditional remove schema, exact managed-allocation admission, stable acceptance result | eligibility, exact path, ineligible target, duplicate-call, activity, and wake tests |
| Removal admission and execution | `/root` | `azents/services/session_git_worktree/**`, allocation and Project repositories | pinned remove action, Runtime and context authority | current allocation revalidation, inspect, dirty/force decision, branch-preserving Runner removal | clean, dirty, force, drift, ambiguous, replay, and cancellation tests |
| Path claims and migration | `/root` | core enum, RDB enum migration, path-claim repository and tests | existing manual/archive claim model | `agent_action` owner kind and action-owned claim acquire/release | migration, claim collision, takeover, and release tests |
| Project and Skill mutation | `/root` | existing Project, Catalog, and Skill integration points plus focused tests | confirmed Runner removed/already-absent result | Project/Catalog removal, Skill `latest` invalidation, cleaned allocation evidence | mutation ordering, failure preservation, and continuation evidence tests |
| Worker and projection integration | `/root` | existing mailbox/worker/live integration and focused tests where required | registered remove action and bridge result | remove dispatch, bounded terminal continuation, fresh-Run handoff | executor, public-projection exclusion, and continuation tests |

- Integration order: enum migration and typed claim owner → Toolkit eligibility and exact allocation admission → mailbox promotion and worker dispatch → pinned authority revalidation → path claim → Runner inspection → dirty/force policy → Runner checkout removal without branch deletion → Project/Catalog/Skill mutation → cleaned allocation and terminal continuation → recovery and archive-skip validation
- Independent review: `hardtack` reviews the stable Phase 3 diff read-only against Requirements, ADR, approved Design revision 2 M1/M2/M7/M8/M9, this plan, Phase 1 and Phase 2 interfaces, and current Specs; output is limited to authority gaps, security/data-loss, destructive Git safety, dirty/force behavior, path-claim concurrency, Project/Skill state inconsistency, branch deletion, recovery/exactly-once failure, removal-obligation failure, or material scope drift
- Final validation: generated migration and one-head checks; `uv run ruff format --check .`; `uv run ruff check .`; `uv run ty check --error-on-warning`; targeted Toolkit, repository, migration, service, worker, and Runtime pytest; relevant broader backend pytest; `git diff --check`; and repository pre-commit hooks on the stable diff
- Scope-drift check: all approved Phase 3 removal behavior is covered; no branch deletion, ordinary Project deletion authority, unmanaged discovery-based removal, compatibility fallback, fixed Workspace root, E2E, Spec promotion, or unrelated cleanup behavior is added
- Context checkpoint: Phase 3 ends with Agents able to remove only current-Session managed worktree Projects, safely refuse or explicitly force dirty checkout removal, preserve the branch, refresh Project and Skill context, and continue in a fresh Run; Phase 4 consumes the complete lifecycle for deterministic E2E, Living Spec promotion, snapshot implementation dates, and plan cleanup

## Phase Checkpoint

- Completed behavior: the Toolkit conditionally projects exact managed-worktree removal; admission pins the current Session Project and allocation; worker execution revalidates Runtime, Workspace, allocation, and Project authority; PostgreSQL path claims guard Runner inspection and checkout removal; dirty content requires explicit force; confirmed removal deletes only the Project and Catalog entry, invalidates Skill `latest`, marks the allocation `CLEANED`, preserves the Git branch, and produces a fresh-Run continuation.
- Changed interfaces: `RemoveGitWorktreeInput`; `AgentRemoveGitWorktreeAction` execution enablement; `agent_action` path-claim ownership; locked allocation and Project repository reads; Agent claim acquisition, transition, release, and cancellation cleanup.
- Authority and drift: approved Design revision 2 mechanisms `M1`, `M2`, `M7`, `M8`, and `M9` are implemented with `Design delta: None`; static and behavioral evidence confirms no Agent removal branch deletion, arbitrary Project authority, unmanaged discovery removal, compatibility fallback, E2E, or Spec-promotion scope.
- Removal evidence: Agent removal never calls `delete_git_branch`; clean and forced removal tests assert branch preservation; dirty non-force, ambiguous inspection, claim contention, and Runner failure retain Project and allocation ownership; archive and manual cleanup behavior remains independent.
- Review: independent `hardtack` review reported no findings. Residual risks are the general durable-write failure window after an externally confirmed Runner side effect and deterministic Runner/fresh-Run E2E coverage assigned to Phase 4.
- Validation:
  - focused Toolkit, mailbox, Project/claim, worktree service, executor, and migration suites: `192 passed`;
  - full backend suite: `4,296 passed`;
  - PostgreSQL parent, upgrade, downgrade, data-preservation, and re-upgrade migration test: passed;
  - Ruff, formatter, backend `ty --error-on-warning`, Alembic one-head/revision-chain checks, and `git diff --check`: passed;
  - repository pre-commit: passed, including documentation indexes, OpenAPI dump, Python checks, Runtime Control generation, and TypeScript format, lint, and typecheck.
- Fixes discovered during validation: added direct Agent claim lifecycle and mailbox promotion coverage; added migration upgrade/downgrade integration coverage; advanced the existing migration-head assertion to the generated Phase 3 revision.
- Remaining scope: Phase 4 deterministic E2E, Living Spec promotion, snapshot implementation dates, validation consolidation, and temporary plan cleanup.
