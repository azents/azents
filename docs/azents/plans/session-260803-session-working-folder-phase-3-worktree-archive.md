---
title: "Session Working Folder Phase 3 Execution Plan"
created: 2026-08-03
updated: 2026-08-03
tags: [session, workspace, git, archive, cleanup, safety]
---

# Phase Execution Plan

- Phase: `3 — Worktree and Archive Cleanup Safety`
- Branch/base: `feat/session-working-folder-3-worktree-archive` → `feat/session-working-folder-2-runtime-projects`
- PR boundary: Allocate new Session worktrees beneath the persisted Session folder and activate exact, commit-first, symlink-safe archive cleanup without changing archive success semantics.
- Inputs: Phase 1 persisted `SessionAgentContext.working_folder_path` and bounded cleanup state; Phase 2 protected root policy and explicit retry behavior from `b8f249f77`.
- Deliverables:
  - new worktree allocations at `{working_folder_path}/worktrees/{repository_leaf}`;
  - explicit new-versus-legacy allocation/cleanup classification, retaining stored legacy paths unchanged;
  - archive transaction marks folder cleanup pending before post-commit external work;
  - after commit, every eligible typed Git cleanup runs once, followed by one exact Session-folder delete regardless of Git outcome;
  - bounded terminal cleanup result persistence without changing archive success;
  - delete-specific Runtime resolution uses lexical `lstat`: delete a root symlink as a link and never follow descendant symlinks;
  - regression proof that restore recovers no bytes and retention purge remains database-only.
- Non-goals:
  - changing the canonical context path, action retry policy, Projects manifest, protected-root policy, or public retry API;
  - contract migration, current-Spec promotion, plan cleanup, Runtime reset, automatic cleanup retries, or purge-time filesystem work;
  - deriving or rewriting legacy allocation paths.
- Interfaces:
  - `SessionAgentContext.working_folder_path` remains sole destructive authority;
  - existing allocation rows retain their recorded path; only newly allocated worktrees use the Session-folder subtree;
  - archive commits state before any Git/Runtime I/O and archive success is not reversed by cleanup outcomes;
  - folder cleanup invokes one exact owned-path deletion and does not follow symlinks;
  - purge receives no filesystem/Git/Runtime participant.
- Approved Design mechanisms: `M7`, `M8`, `M9`; regression preservation of `M11`.
- Authority references: `session-260803/REQ-5`, `REQ-6`, `REQ-7`; `session-260803/ADR-D1`, `ADR-D2`, `ADR-D3`; approved Design revision 1 and implementation-plan Phase 3.
- Design delta: `None`
- Removal obligations:
  - remove new-allocation dependence on the legacy managed-worktree root;
  - remove legacy-parent deletion from new-path cleanup while preserving legacy cleanup coverage;
  - remove symlink-following delete resolution at the Session folder root;
  - replace archive Git-only post-commit cleanup with typed Git cleanup followed by exact folder deletion.
- Absence verification:
  - new allocation tests assert stored-folder worktree paths; legacy rows keep recorded paths;
  - new cleanup tests prove no legacy-parent removal while legacy cleanup remains covered;
  - root-symlink test preserves the external target and descendant-symlink test preserves the sentinel;
  - archive tests observe commit before I/O, folder deletion after Git success and failure, and unchanged archive success;
  - purge tests prove no Runtime, Git, or filesystem call.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Worktree allocation and classification | `/root` | `python/apps/azents/src/azents/services/session_git_worktree/**`; allocation/cleanup repos and tests | Stored working-folder context | New paths under canonical folder; legacy classification | New/legacy allocation and cleanup tests |
| Archive lifecycle cleanup | `/root` | `python/apps/azents/src/azents/services/chat/**`; archive/retention tests; cleanup service | Bounded context cleanup state | Commit-first state, once-only Git/folder attempts, bounded outcomes | Transaction ordering, failure continuation, restore/purge regressions |
| Runtime lexical deletion | `/root` | `python/apps/azents/src/azents/runtime/**`; Runner delete tests | Exact owned folder path | `lstat` root and descendant symlink safety | Symlink sentinel, absent target, Runtime-unavailable tests |
| Integration and generated artifacts | `/root` | Changed backend tests, OpenAPI/client artifacts only if public contract changes, phase plan | All workstreams | Stable destructive-safety evidence | Ruff, Pyright, focused suites, OpenAPI/client checks if needed, `git diff --check` |

- Integration order:
  1. Identify current worktree allocation/cleanup classifications and add new/legacy path tests.
  2. Move new allocations to the stored Session folder without changing existing rows.
  3. Add commit-first archive cleanup state and post-commit Git/folder sequencing.
  4. Make delete resolution lexical and prove root/descendant symlink safety.
  5. Prove restore and database-only purge preservation, then run final validation and scope audit.
- Independent review:
  - Exact reviewer: GitHub reviewer `hardtack`.
  - Scope: complete Phase 3 diff against `M7`, `M8`, `M9`, `M11`, this plan, and the approved snapshot.
  - Criteria: exact stored path authority; no legacy rewrite; commit precedes I/O; each cleanup attempt occurs once; Git failure does not suppress folder deletion; no symlink traversal; no purge filesystem participant; archive semantics remain stable.
  - Output: grounded Critical/Warning findings or explicit approval.
- Final validation:
  - focused worktree allocation/cleanup, archive lifecycle, Runtime delete/symlink, restore, and retention-purge tests;
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`;
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`;
  - `cd python/apps/azents && uv run pyright`;
  - OpenAPI/client generation only if a public contract changes;
  - `git diff --check` and pre-commit validation.
- Scope-drift check:
  - map every behavior to `M7`, `M8`, `M9`, or preservation of `M11`;
  - remove path derivation, legacy rewrites, selective folder preservation after Git failure, automatic retries, reset coordinators, public retry changes, migration tightening, and purge filesystem work;
  - return to feature design for a new ownership source, cleanup mode, archive semantic, or destructive scope.
- Context checkpoint:
  - record new/legacy path evidence, archive commit-before-I/O and failure continuation evidence, symlink sentinel evidence, bounded cleanup outcomes, restore/purge proof, review result, validation commands, Phase 4 prerequisites, risks, and blockers.
