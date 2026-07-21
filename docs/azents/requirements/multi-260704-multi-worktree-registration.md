---
title: "Multi-Worktree Registration Historical Requirements Reconstruction"
created: 2026-07-04
implemented: 2026-07-04
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: multi-260704
historical_reconstruction: true
migration_source: "docs/azents/design/multi-worktree-registration.md"
---

# Multi-Worktree Registration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `multi-260704`
- Source: `docs/azents/design/multi-260704-multi-worktree-registration.md`
- Historical source date basis: `2026-07-04`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents can create a new AgentSession in one Azents-owned Git worktree, but the current `session_git_worktrees` model has a unique `session_id` constraint and the worktree initialization runner assumes one allocation per session. Existing sessions can register ordinary existing folders as Projects, but they cannot request additional Azents-owned Git worktrees from the Project panel.

Users need to attach multiple Git worktree Projects to an existing active session without creating a new session for each isolated branch/workspace.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Allow an active AgentSession to own multiple Git worktree allocations.
- Reuse the existing `SessionInitialization` lifecycle as the session-level sequential workspace preparation queue.
- Register each completed worktree as a normal `SessionWorkspaceProject` so prompt/tool Project scope continues to use the existing Project registry.
- Keep Runner Git operations typed and reuse existing `list_git_refs`, `create_git_worktree`, `remove_git_worktree`, and `delete_git_branch` operations.
- Keep this feature focused on multiple worktree registration, not a broad Project cleanup redesign.

## Non-goals

- Do not introduce a separate generic background-job lifecycle.
- Do not replace `session_workspace_projects` as the prompt/tool Project boundary.
- Do not let agents create worktrees through tool calls.
- Do not redesign archive cleanup beyond iterating all session-owned worktree allocations.
- Do not add setup scripts or dependency bootstrap steps.

## Requirements

- Runtime fixture with a Git repository under the Agent Workspace.
- Ability to preview refs and create multiple branch-backed worktrees in the same runtime.
- Test evidence should include created session ID, worktree IDs, Project paths, and initialization status transitions.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
