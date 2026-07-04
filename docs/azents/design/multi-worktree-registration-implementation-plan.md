---
title: "Multi-Worktree Registration Implementation Plan"
created: 2026-07-04
tags: [backend, frontend, runtime, session, workspace, git]
---

# Multi-Worktree Registration Implementation Plan

## Summary

This plan ships [Multi-Worktree Registration](multi-worktree-registration.md): existing active sessions can register multiple Azents-owned Git worktree Projects. The implementation reuses the session `SessionInitialization` lifecycle as the sequential workspace preparation queue.

## PR Stack

| PR | Title | Scope |
| --- | --- | --- |
| 1 | `Multi-worktree registration [1/7]: Design` | Design document and docs index |
| 2 | `Multi-worktree registration [2/7]: Implementation plan` | This phased plan |
| 3 | `Multi-worktree registration [3/7]: Backend queue and API` | DB migration, repositories, service queue, API, generated clients, backend tests |
| 4 | `Multi-worktree registration [4/7]: Project panel worktree attach UI` | Existing-session Project panel attach flow and Storybook states |
| 5 | `Multi-worktree registration [5/7]: Validation` | Planned validation evidence, E2E/testenv run results, and fixes found during validation |
| 6 | `Multi-worktree registration [6/7]: Spec promotion` | Living spec updates and design implementation marking if validation is complete |
| 7 | `Multi-worktree registration [7/7]: Cleanup` | Remove stale implementation plan artifacts after specs are current |

## Phase Dependencies

- Phase 3 depends on the design and this plan.
- Phase 4 depends on Phase 3 generated public client changes.
- Phase 5 depends on backend and frontend behavior being available.
- Phase 6 depends on validation evidence from Phase 5.
- Phase 7 depends on Phase 6 making specs the current source of truth.

## Phase 3: Backend Queue and API

### Data changes

- Generate an Alembic migration.
- Remove `uq_session_git_worktrees_session_id`.
- Add nullable `session_workspace_project_id` FK to `session_workspace_projects.id` with `ON DELETE SET NULL`.
- Add explicit indexes:
  - `ix_session_git_worktrees_session_id_status`
  - `ix_session_git_worktrees_session_workspace_project_id`
- Update `db-schemas/rdb/revision`.

### Repository changes

- Add `SessionGitWorktreeRepository.list_by_session_id(...)`.
- Add `get_by_id_for_session(...)`.
- Add `link_workspace_project(...)`.
- Update existing single-row call sites that use `get_by_session_id(...)`.

### Service changes

- Add an existing-session attach method to `SessionGitWorktreeService`.
- Append `worktree_id`-scoped step keys to the session's existing initialization.
- Allocate step `sequence` values after the current max sequence.
- Replace the single-allocation runner entrypoint with a session queue processor that handles pending worktree groups in order.
- Keep the existing run gate: initialization is `pending` or `running` while queued worktree registration is in progress, then returns to `ready` after the queue drains.
- Archive cleanup iterates all non-cleaned allocations for the session.

### API and generated clients

- Add `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/git-worktrees`.
- Return the created worktree allocation and current initialization projection.
- Regenerate public API clients.
- Add tRPC procedure wrapping the generated public client.

### Backend tests

- Repository allows multiple worktree rows per session.
- Attach API creates allocation and scoped initialization steps.
- Queue processor registers two worktrees in sequence.
- Run gate blocks while queued worktree registration is pending/running.
- Archive cleanup requests all session-owned allocations.

## Phase 4: Project Panel Worktree Attach UI

- Add a `New worktree` action to the existing session Project panel.
- Reuse or extract Git source/ref selector UI from the new-session flow.
- Use existing `previewAgentGitRefs` query for source Project ref discovery.
- Add mutation for existing-session worktree attach.
- Invalidate Project queries and initialization/live queries after attach and ready transitions:
  - `listAgentProjects`
  - `getSessionProjectBrowserManifest`
  - `listSessionEvents` or latest live snapshot query as needed
- Add Storybook states for selecting source/ref, loading refs, attach pending, and failure.

## Phase 5: Validation

### E2E primary validation matrix

| Behavior | Expected evidence |
| --- | --- |
| Attach first worktree to existing session | Created worktree appears in Project panel after initialization reaches ready |
| Attach second worktree to same session | Same session has two worktree-created Project rows |
| Sequential queue | Two quick attach requests complete in sequence and initialization returns to ready |
| Run gate | Message sent while registration is pending remains pending until setup completes |
| Failure path | Invalid ref records scoped initialization failure and creates no Project row |

### Validation evidence format

- Commands and working directories.
- Runtime fixture/prerequisite snapshot.
- Agent/session/worktree IDs.
- API response snippets for attach and Project list.
- UI screenshot or DOM assertion summary for Project panel states.
- Comparison table between implemented behavior and current specs.

### Fixture requirements

- A ready Agent Runtime with a Git repository under `/workspace/agent`.
- The repository must have at least one branch/ref that can be used for worktree creation.
- The environment must allow multiple branch-backed worktrees in the same source repository.

### CI policy

- Backend repository/service/API tests must run in normal CI.
- TypeScript format/lint/typecheck/build must pass after frontend changes.
- Runtime-backed E2E can be optional only if the CI runner cannot provide a ready runtime fixture; the validation PR must record that prerequisite gap explicitly.

## Phase 6: Spec Promotion

Spec impact candidates:

- `docs/azents/spec/domain/conversation.md`
  - Existing-session worktree attach API.
  - Multiple `SessionGitWorktree` rows per session.
  - Initialization queue behavior.
- `docs/azents/spec/domain/workspace.md`
  - Worktree-created Project registration behavior for existing sessions.
  - Project browser behavior after multiple worktrees.
- `docs/azents/spec/flow/agent-execution-loop.md`
  - Run gate while workspace update initialization is pending/running.
- `docs/azents/spec/flow/chat-session-resync.md`
  - Initialization live projection for appended worktree registration steps.
- `docs/azents/spec/flow/agent-runtime-control.md`
  - No new Runner operation types expected, but confirm typed Git operation contract still covers the feature.

If validation is complete, mark `multi-worktree-registration.md` as implemented with the implementation date.

## Phase 7: Cleanup

- Remove this implementation plan if specs are current and the design is marked implemented.
- Keep the design document as historical rationale.
- Do not mix cleanup with behavior changes.

## Known Blockers

None known. Runtime-backed E2E depends on a ready runtime fixture with a Git repository; if unavailable, Phase 5 must record the prerequisite gap and rely on API/service coverage plus optional live validation evidence.

## Rollout Notes

- Existing sessions with a single worktree remain valid after the unique constraint is removed.
- Generated API clients must be regenerated in the backend/API phase.
- Cleanup authority remains based on `session_git_worktrees` ownership rows.
