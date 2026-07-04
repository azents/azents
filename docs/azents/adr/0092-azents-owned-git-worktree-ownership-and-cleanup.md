---
title: "ADR-0092: Azents-Owned Git Worktree Ownership and Cleanup"
created: 2026-07-03
tags: [architecture, backend, runtime, git, session]
---

# ADR-0092: Azents-Owned Git Worktree Ownership and Cleanup

## Context

Azents sessions can currently register explicit Project paths under the Agent Workspace. Those Project rows define prompt/tool Project scope, but they do not mean Azents created, owns, or may delete the underlying filesystem path.

The new worktree flow creates an isolated Git worktree for a new non-primary AgentSession from an explicit source Project and starting ref. The created worktree should become the session Project after setup succeeds and should be removed when the session is archived or deleted.

This introduces destructive cleanup behavior. Cleanup safety must be based on explicit ownership records, not on arbitrary path prefixes, Project rows, or catalog entries.

## Decision

### ADR-0092-D1 — Separate worktree ownership from Project registration

`session_workspace_projects` remains a session Project registry and prompt/tool scope boundary. It does not store Git ownership metadata and is not used as cleanup authority.

Azents-owned worktree allocation and cleanup state is stored in a separate `session_git_worktrees` model. This model records source Project path, starting ref, resolved base commit, worktree path, branch name, ownership marker, status, failure summary, cleanup summary, and timestamps.

### ADR-0092-D2 — Create branch-backed Azents-owned worktrees by default

Worktree mode creates a branch-backed Git worktree by default. The runner executes an argv equivalent of:

```console
git worktree add -b <branch_name> <worktree_path> <starting_ref>
```

The allocation row stores the exact branch name and worktree path. Cleanup never reconstructs these values from current naming rules.

### ADR-0092-D3 — Use an Azents management root but never infer ownership from path alone

Azents-owned worktrees live under an Azents management root such as:

```text
/workspace/agent/.azents/worktrees/{session_handle}/{repo_leaf}
```

The `{session_handle}` component is the durable `agent_sessions.handle` value defined by ADR-0091. Worktree path and branch naming use the stored handle and never derive names from session title, prompt text, or raw UUID strings.

The management root is a safety boundary and organizational convention. It is not sufficient authority to delete a path. Deletion requires a matching `session_git_worktrees` row and ownership validation.

The MVP does not add a user-facing validator that rejects manual Project registration under `/workspace/agent/.azents/**`.

### ADR-0092-D4 — Register worktree Projects only after Git setup succeeds

A worktree path is registered in `session_workspace_projects` only after Git worktree creation succeeds. Worktree setup is a blocking `SessionInitialization` step.

On success, backend registers the worktree path as a session Project and upserts `agent_project_catalog` so Project Browser manifests can show the worktree path. Worktree-created Projects do not update `agent_project_presets` or `agent_project_defaults`.

### ADR-0092-D5 — Archive/delete cleanup runs asynchronously and is best-effort in the MVP

Archive marks matching worktree allocations `cleanup_pending`, soft-archives the session, and enqueues cleanup work. The archive HTTP request is not held open while Git cleanup runs.

Cleanup attempts to remove the Azents-owned worktree, delete the Azents-created branch, and remove the worktree path from the Agent Project catalog.

Cleanup failure does not block archive in the MVP. Failure marks the worktree allocation `cleanup_failed`, stores a user-safe cleanup summary, and leaves enough metadata for manual cleanup guidance.

Hard delete must not erase ownership metadata before cleanup has completed or recorded failure. A delete request for a session with owned worktrees must either run cleanup first or transition through a delete-requested/tombstone state that preserves the allocation metadata until cleanup reaches `cleaned` or `cleanup_failed`.

### ADR-0092-D6 — Destructive cleanup requires explicit ownership validation

Deletion is allowed only when all of these are true:

- a matching `session_git_worktrees` row exists;
- the requested path equals the recorded `worktree_path`;
- the path is under the expected Azents worktree root;
- the branch equals the recorded `branch_name`;
- the branch ownership marker says Azents created the branch;
- cleanup is requested for the owning session through archive, delete, retry cleanup, or a manual cleanup action.

Reserved-root membership, `session_workspace_projects`, and `agent_project_catalog` are not deletion authority.

### ADR-0092-D7 — Git worktree operations are typed runner operations

Git worktree operations are typed runner operations, not arbitrary backend shell strings and not agent tool calls.

The runtime-control protocol, client, server mapping, backend operation client, runner adapter, and runner implementation must represent the Git operation payloads and semantic results. The runner internally executes argv-based Git commands and streams command output to the initialization lifecycle.

### ADR-0092-D8 — Keep catalog metadata out of worktree ownership

`agent_project_catalog` remains an Agent-scoped Project path and filesystem status read model. Worktree ownership, cleanup state, branch ownership, and cleanup authority remain in `session_git_worktrees`.

Worktree-created paths are still upserted into the catalog after setup succeeds so Project Browser manifests can show the path. The catalog row does not get a worktree ownership source field in the MVP. If Project Browser needs a worktree badge, cleanup status, or worktree-specific capabilities, the manifest service should project that information by joining against `session_git_worktrees`, not by treating the catalog as lifecycle authority.

### ADR-0092-D9 — Git source/ref discovery is a separate typed preview operation

Worktree session creation uses an explicit `source_project_path` and `starting_ref`. The source path may be selected from backend Project Browser or Agent Project catalog candidates before the target session exists. It does not need to be registered on the new session before creation.

The backend exposes a Git ref discovery preview API backed by a typed `list_git_refs` runner operation. The UI uses it to load branches/tags/default branch after a source Project is selected. The create request still sends `starting_ref` explicitly, and `create_git_worktree` revalidates the ref before creating the worktree.

## Consequences

- Session Project registry remains a path binding model and does not become a Git ownership model.
- Cleanup can safely delete Azents-owned worktrees and branches while leaving manually registered Projects untouched.
- Worktree creation success must update both session Project bindings and the Agent Project catalog, while intentionally skipping presets/defaults.
- The Agent Project catalog schema remains focused on path/status projection; worktree-specific UI metadata is projected from `session_git_worktrees` when needed.
- Runtime-control protocol changes are required for typed Git operations.
- Archive/delete logic needs a cleanup service boundary and a background cleanup execution path around the existing soft archive/delete behavior.
- Manual cleanup guidance can be shown from allocation metadata when cleanup fails.
- Hard delete of sessions with worktrees needs a retention/tombstone flow or pre-delete cleanup to avoid losing ownership authority.

## Alternatives

### Store worktree ownership only in initialization descriptors

Rejected. Initialization descriptors are useful snapshots, but cleanup and ownership queries need a structured authoritative model.

### Use `session_workspace_projects` as cleanup authority

Rejected. Project rows mean a path is in scope for a session. They do not mean Azents created the path or may delete it.

### Detached worktrees by default

Rejected. Branch-backed worktrees give sessions a natural edit/commit/PR path and make branch ownership explicit.

### Update presets/defaults for worktree paths

Rejected. Worktree paths are ephemeral. They should be visible for the active session and Project Browser catalog, but they should not become default selections for future sessions.

### Fail archive when cleanup fails

Rejected for MVP. Archiving should not be blocked by transient Git/process cleanup failures. Users get cleanup status and manual guidance instead.

### Use generic shell/process execution for Git operations

Rejected as the target design. Typed operations provide semantic validation, safer payload handling, and cleanup-specific failure classification.
