---
title: "Session Git Worktree Lifecycle Research"
created: 2026-07-03
tags: [architecture, backend, runtime, git, session]
---
# Session Git Worktree Lifecycle Research

This note captures pre-design research and discussion for creating Git worktrees when a non-primary AgentSession starts, binding the worktree as the session Project, and cleaning it up when the session is archived.

This is not the final design. Use this note as input for a later design document under `docs/azents/design/`.

## Problem

Azents currently lets a non-primary AgentSession select explicit Project paths under `/workspace/agent`, but those paths are normal session workspace paths. The new direction is to support Git-backed isolated session workspaces:

1. Create a Git worktree when a session starts.
2. Register that worktree path as the session Project.
3. Delete the Azents-owned worktree when the session is archived.

The design must preserve the current Project model while adding a separate lifecycle authority for worktree allocation and cleanup.

## Current Azents Evidence

- `ChatSessionService.create_team_session()` currently accepts `project_paths`, normalizes them, creates an `agent_sessions` row, then creates `session_workspace_projects` rows.
- `ChatSessionService.archive_agent_session()` currently validates access, blocks primary/running sessions, and transitions the session to archived. It does not perform filesystem cleanup.
- `session_workspace_projects` is a path registry for Projects, not a Git/worktree abstraction.
- `SessionWorkspaceProjectService` validates Project paths under `/workspace/agent` and syncs skill projection after Project changes.
- Main now includes the Workspace Project Browser work. `agent_project_catalog` is an Agent-scoped reusable Project path candidate and filesystem status projection. It is a UI/read-model projection, not the source of prompt Project eligibility.
- Main now includes backend-owned Project browser manifest endpoints for existing sessions and pre-session previews. This is important for future worktree-created Project candidates.
- [backend-260703/ADR](../adr/backend-260703-backend-browser-manifest.md) already names future worktree creation success as a Project filesystem status sync trigger.

Relevant code paths:

- `python/apps/azents/src/azents/services/chat/__init__.py`
- `python/apps/azents/src/azents/services/session_workspace_project/__init__.py`
- `python/apps/azents/src/azents/repos/session_workspace_project/__init__.py`
- `python/apps/azents/src/azents/rdb/models/session_workspace_project.py`
- `python/apps/azents/src/azents/api/public/chat/v1/__init__.py`
- `python/apps/azents/src/azents/rdb/models/agent_project_catalog.py`
- `python/apps/azents/src/azents/repos/agent_project_catalog/__init__.py`
- `python/apps/azents/src/azents/services/agent_project_catalog/__init__.py`
- `python/apps/azents/src/azents/services/project_browser_manifest.py`
- `docs/azents/adr/backend-260703-backend-browser-manifest.md`
- `docs/azents/design/workspace-project-browser.md`

## Codex Research

Research was refreshed against `openai/codex` `origin/main` at commit `da4c8ca57` after the initial CLI/core-only inspection missed the Desktop App worktree UX.

Corrected finding: Codex Desktop App does have a managed local worktree creation flow. The exact Desktop UI implementation is not fully visible in the public Rust app-server code, but public issue reports in `openai/codex` provide concrete evidence of the shipped behavior:

- Codex App has a `New worktree` mode when starting a local conversation.
- It creates worktrees under `~/.codex/worktrees/...`.
- Observed worktree creation uses detached Git worktrees, for example `git worktree add --detach /Users/.../.codex/worktrees/... <ref>`.
- Worktree setup output is surfaced to the user. A remote-only branch failure showed `Worktree setup failed.`, `[info] Starting worktree creation`, Git's `fatal: invalid reference: ...`, and `[stderr] git worktree add failed: ...`.
- Creation can partially succeed: Git worktree exists and appears in `git worktree list`, but Codex thread/session state may fail to materialize, leaving an orphaned worktree.
- Codex-managed worktrees are expected by users/docs to be deleted automatically when the associated thread is archived, though there are reports where archive left the worktree and local environment resources behind.
- The App currently appears to default to detached worktrees even when a local branch is selected as the starting branch, which has caused confusion for branch-backed workflows.

The public app-server code still matters because it shows the protocol shape Codex can use to make this UX transparent:

- `thread/start`, `thread/resume`, and `thread/fork` accept `cwd` and experimental `runtimeWorkspaceRoots`, so a client-owned worktree path can become the thread runtime workspace.
- `command/exec` runs an argv command in the server sandbox without creating a thread or turn, supports streaming stdout/stderr through `command/exec/outputDelta`, and requires a client-supplied process id for streaming.
- In-turn command execution maps `ExecCommandBegin` to `item/started`, `ExecCommandOutputDelta` to `item/commandExecution/outputDelta`, and `ExecCommandEnd` to `item/completed`, which explains the transparent command/output UX the App can reuse for setup operations.
- `AgentStatus::PendingInit` exists for agents waiting for initialization; thread status and item events provide separate lifecycle surfaces for pending setup and visible command execution.
- Linked Git worktrees are recognized for trust and hook discovery. Hook declarations for linked worktrees come from the root checkout `.codex/` folder so one repo has one authoritative hook definition and trust state.

Implication for Azents: the Codex-like UX is stronger than a hidden backend job. Azents should model workspace preparation as visible initialization work: keep the user's first message pending, emit explicit setup steps and streamed command output, then start the agent turn only after the worktree is ready. Worktree creation should still be an owned lifecycle operation with rollback/cleanup state, not an ordinary Project registration.

Useful Codex evidence:

- `codex-rs/app-server-protocol/src/protocol/v2/thread.rs`
- `codex-rs/app-server-protocol/src/protocol/v2/command_exec.rs`
- `codex-rs/app-server-protocol/src/protocol/event_mapping.rs`
- `codex-rs/app-server-protocol/src/protocol/item_builders.rs`
- `codex-rs/app-server/src/request_processors/command_exec_processor.rs`
- `codex-rs/app-server/src/command_exec.rs`
- `codex-rs/app-server/README.md`
- GitHub issue `openai/codex#16936`: worktree creation can time out after Git succeeds, leaving orphaned worktrees with no thread/session state.
- GitHub issue `openai/codex#22635`: remote-only branch worktree setup failure shows visible setup logs and `git worktree add --detach` command behavior.
- GitHub issue `openai/codex#19480`: archive expected to delete Codex-managed worktrees and run cleanup, but reported stale worktree/resources.
- GitHub issue `openai/codex#30954`: selecting a local branch still created a detached worktree.

## OpenCode Research

Research was done against `sst/opencode` `origin/dev` at commit `3adfb970bf071419599ca016ebd2b08361fa28e9`.

OpenCode is closer to the local worktree UX:

- It has a Project copy strategy with `git_worktree` as a strategy.
- Core worktree creation uses `git worktree add --detach <dir> HEAD`.
- Legacy/experimental worktree service creates a dedicated worktree root, derives branch/directory names, avoids collisions, and emits ready/failed lifecycle state.
- New session UX can select main, existing sandbox, or create a worktree before starting the session.
- Deletion can remove worktree directory and branch, but its forceful behavior should not be copied directly into Azents without safety constraints.

Implication for Azents: OpenCode is useful for local creation/cleanup mechanics, while Codex is more useful for the higher-level environment/workspace binding model.

Useful OpenCode files:

- `packages/core/src/project.ts`
- `packages/core/src/project/copy.ts`
- `packages/core/src/project/copy-strategies.ts`
- `packages/core/src/git.ts`
- `packages/opencode/src/worktree/index.ts`
- `packages/app/src/components/prompt-input/submit.ts`

## Decisions Discussed So Far

These started as discussion checkpoints. Items marked `Accepted` reflect decisions made in the design discussion and should be carried into the later design document.

### Accepted: Use Async Worktree Allocation With Pending Workspace

New session creation should create the AgentSession and pending worktree allocation first, then return before Git worktree creation completes. The UI should represent workspace preparation as pending and refresh when the allocation becomes ready.

Rationale:

- Worktree creation is a runtime/runner side effect, not a simple DB insert.
- Slow Git checkout, branch creation, or bootstrap should not make session creation depend on a long synchronous request.
- This matches Codex/OpenCode-style separation between session/thread identity and environment/workspace readiness.
- It also aligns with the Project Browser/Catalog model, where path candidates and filesystem status projection can exist before ready Project registration.

Policy implication:

- Runs that require the worktree Project should wait for or reject until the allocation is ready.
- When the allocation succeeds, the service registers `session_workspace_projects`, updates `agent_project_catalog`, and refreshes Project browser state.
- When the allocation fails, the session remains created but exposes a workspace preparation failure state that can be retried or archived.

### Accepted: Create a Session Branch by Default

New worktree allocation should create an Azents-owned branch by default instead of starting detached.

Policy:

- Initial worktree mode is `branch`.
- Branch names use an Azents-owned namespace, tentatively `azents/{session_handle}` with collision-safe suffixing if needed.
- The allocation record stores the selected base ref, resolved base commit, branch name, and whether Azents created the branch.
- Worktree creation should use argv-based Git execution, equivalent to `git worktree add -b <branch> <path> <base_ref>`.
- Archive cleanup may delete only Azents-created branches that still match the allocation record and cleanup policy.

Rationale:

- OpenCode's product worktree flow defaults to a per-worktree branch and cleans up that branch with the worktree.
- A branch-backed session makes code edits, commits, diffs, and future PR workflows natural from the start.
- The branch namespace gives users and operators an obvious Git handle for the session workspace.
- Cleanup remains safe because branch ownership is explicit in the allocation record rather than inferred from `session_workspace_projects`.

### Accepted: Force-Remove Dirty Worktrees During Archive Cleanup

Archive cleanup should remove Azents-owned worktrees even when they contain modified or untracked files.

Policy:

- Archive may force-remove worktrees that have a matching allocation record, an expected reserved-root path, and an Azents-created branch ownership marker.
- Dirty-state detection should be recorded before deletion for audit/debug output when available.
- The UI/API should make the destructive nature of archive cleanup clear for sessions with Azents-owned worktrees.
- Force removal must not apply to manually registered Projects, catalog-only paths, or paths outside the reserved root.

Rationale:

- Session worktrees are Azents-owned ephemeral workspaces, not user-selected source Projects.
- A branch-backed worktree default can otherwise leave many stale worktrees behind when sessions are archived.
- OpenCode uses forceful worktree removal for its owned worktree lifecycle; Azents can follow that model while adding allocation-row and reserved-root safety checks.
- Safety should come from strict ownership validation, not from preserving dirty ephemeral directories by default.

### Accepted: Delete Azents-Created Branches and Catalog Entries After Archive Cleanup

Archive cleanup should remove the Git and catalog projection for Azents-created session worktrees.

Policy:

- After successful worktree removal, delete the Azents-created branch recorded on the allocation row.
- Delete the corresponding `agent_project_catalog` entry for the worktree path instead of keeping an archived/unavailable tombstone.
- Delete the corresponding `session_workspace_projects` registration as part of archive cleanup or mark it inactive according to the existing session archive model.
- Keep historical information in session/worktree allocation audit fields rather than in the active project browser catalog.
- Branch deletion must be skipped if ownership validation fails, the branch no longer matches the allocation record, or a future explicit preserve/PR policy says it is user-owned.

Rationale:

- Session worktrees are Azents-owned ephemeral workspaces.
- Keeping archived worktree paths in the active project browser catalog would make pre-session project selection noisy.
- Deleting branches keeps the repository branch namespace from growing for every archived session.
- Future preserve semantics can be added as an explicit policy without changing the default cleanup model.

### Accepted: Do Not Add a Reserved-Path Registration Validator in the MVP

Azents should not add a special user-facing validator that rejects manual Project registration under `/workspace/agent/.azents/**` for the MVP.

Policy:

- Reserved-root membership is a cleanup safety signal, not a user registration rule.
- Manual Project registration can continue to use the existing path validation/catalog behavior.
- Archive cleanup must still require a matching Azents-owned allocation row before deleting any path or branch.
- If user registration under the management root causes Project Browser noise in practice, add a validator later as a UX hardening change.

Rationale:

- Deletion safety should depend on explicit worktree allocation ownership, not on assuming every reserved-root path is internal.
- Avoid adding an extra special-case path policy unless there is a concrete UX or security need.
- This keeps the MVP smaller while preserving safe cleanup boundaries.

### Separate Worktree Allocation From Project Registry

Do not turn `session_workspace_projects` into a Git model. Add a separate allocation record, tentatively `session_git_worktrees`, and register the resulting worktree path as a Project only after allocation succeeds.

Rationale:

- Project registry answers what paths are active Projects for prompt/tool instruction scope.
- Worktree allocation answers what Azents created, owns, and may delete.
- Agent Project catalog answers what Project path candidates and filesystem status projections are reusable in UI/pre-session flows.
- Archive cleanup must use the allocation table, not arbitrary Project paths or catalog entries.

### Include Agent Project Catalog In The Success Path

After main introduced the Workspace Project Browser, worktree creation success should update both the session Project registry and the Agent Project catalog.

Expected successful allocation effects:

1. Mark `session_git_worktrees` allocation ready.
2. Upsert `agent_project_catalog` for `agent_id + path` with available or unchecked status depending on whether the runner operation already proved the directory exists.
3. Create `session_workspace_projects` row for prompt/tool Project scope.
4. Refresh `agent_project_presets` and `agent_project_defaults` only if the worktree should be reusable/default-selected in the same way as explicit user-selected Projects.
5. Trigger Project browser manifest/status refresh behavior through the same catalog path used by existing project registration and preview flows.

### Use an Azents-Owned Reserved Root

Recommended root:

```text
/workspace/agent/.azents/worktrees/{session_handle}/{project_handle}
```

Rejected locations:

- Repository-internal worktree directories, because they complicate nested worktree behavior, Git status, instruction discovery, and cleanup.
- Repository sibling directories, because they mix user-owned and Azents-owned paths and weaken cleanup safety.
- Generic `/workspace/agent/worktrees`, because it can collide with user-created Projects unless reserved separately.

Required policy:

- `/workspace/agent/.azents` is an Azents management path for allocation and cleanup safety.
- User-facing Project registration does not need a special validator for this root in the MVP.
- Cleanup may delete only paths with a matching allocation row and expected reserved-root prefix; reserved-root membership alone is never enough to delete a path.

### Avoid Raw Session UUIDs In Paths

AgentSession IDs are UUID7 and are hard to read in filesystem paths. The worktree directory name should not be the raw `agent_sessions.id`.

Discussed direction:

- Keep `agent_sessions.id` as the DB identity only.
- Add a human-readable session handle for filesystem/display use.
- The handle should be stable for the session and generated at session creation.

### Use Three Random Words For Session Handle

Claude-style three-word handles are preferred for readability, for example:

```text
brisk-cedar-lantern
```

Proposed path shape:

```text
/workspace/agent/.azents/worktrees/brisk-cedar-lantern/azents
```

Policy:

- The handle is human-readable and stable, but ownership and cleanup authority remain DB-backed.
- Enforce uniqueness with a DB constraint and retry generation on collision.
- Do not derive the handle from session title or user prompt, to avoid title drift and sensitive information in paths.
- For multiple worktrees in one session, use `{session_handle}/{project_handle}`.

## Design Direction

The likely Azents design should follow this flow:

1. Client requests a new session with Git worktree allocation intent, not only static `project_paths`.
2. Server validates user access and source repository metadata.
3. Server creates the AgentSession and a pending worktree allocation row in one DB transaction.
4. Server asks the runtime/runner operation layer to create the worktree using argv-based Git operation semantics.
5. When creation succeeds, server marks allocation ready and registers the worktree path in `session_workspace_projects`.
6. Skill projection is synced after Project registration.
7. On archive, server blocks if the session is running, checks owned allocations, removes worktrees safely, then archives or records cleanup failure depending on policy.

## Open Questions

- Should worktree creation be synchronous in the session create API, or should session creation return a pending workspace state and unblock when ready?
- Should the default worktree be detached at `HEAD`, or should Azents create a branch such as `azents/{session_handle}`?
- Should archive fail when a worktree is dirty, or should archive mark the session archived and leave cleanup pending?
- Should worktree cleanup delete the branch, keep the branch, or make branch deletion an explicit user action?
- How should multiple source repositories per session be represented in the API and UI?
- Where should three-word handle wordlists live, and should handles be globally unique or agent-scoped unique?
- What is the exact runner operation protocol for safe Git commands, timeouts, hook suppression, and stderr classification?

## Safety Requirements

- Use argv-based Git operations, not shell string construction.
- Disable Git hooks for internal Git metadata probes where possible.
- Store source repository identity separately from worktree path.
- Recognize linked worktree `.git` pointer files and common Git dir identity.
- Treat `.git` directory/file/pointer as protected metadata.
- Never delete a path based only on user-supplied Project path.
- Force-remove dirty worktrees only when an authoritative Azents-owned worktree allocation row matches the path, branch, and cleanup policy.
- Surface cleanup failures as a user-visible cleanup_failed/manual-cleanup state instead of blocking archive.

## Needs Verification

- Current runtime/runner operation protocol support for arbitrary Git operations.
- Whether `agent_sessions` should store the three-word session handle or whether a separate table should own it.
- Exact archive semantics if cleanup fails after some worktrees were removed.
- UI requirements for exposing session handle and worktree paths.
- Whether current Project path validation should reject all `/workspace/agent/.azents/**` paths except internally-created allocations.
