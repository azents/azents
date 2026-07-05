---
title: "Existing Session Worktree Registration Design"
created: 2026-07-05
updated: 2026-07-05
tags: [backend, frontend, api, session, workspace, git]
---

# Existing Session Worktree Registration Design

## Overview

This design lets users add an Azents-owned Git worktree Project to an already-existing active
AgentSession from the existing Register Project flow. The UI keeps one Project registration entry
point: users browse folders, Git repository folders are visually identified, and selecting a Git
repository opens a registration modal that can either register the folder directly or create a new
worktree from it.

The backend operation model follows ADR-0094. Creating the worktree is not a new public worktree
endpoint and not a `SessionInitialization` extension. It is a session operation TurnAction represented
by a durable `create_git_worktree` `action_message` input. Existing-session worktree creation therefore
uses the same action execution lifecycle, retry/discard behavior, timeline progress rendering, and
Project context invalidation boundary as new-session worktree setup.

## Problem

Azents supports direct registration of an existing folder as a session Project. It also supports
creating a Git worktree during new-session setup through `create_git_worktree` operation actions.
The missing product workflow is adding another isolated Git worktree to a session that already exists
and may already have transcript history, Project context, Skills, and pending/running action history.

A separate `New worktree` Project-panel button would create a second Project entry point and split the
user's mental model. Users are already in the Project registration surface when they decide whether a
folder should be used directly or as the source for an isolated worktree. The feature should keep that
flow unified while still making the worktree operation explicit and recoverable.

The deletion side also needs a clear policy. If a session can attach an Azents-owned worktree in the
middle of its lifetime, users must be able to remove that worktree later. However, deleting filesystem
state is destructive and must be limited to worktrees with explicit Azents ownership metadata, not
inferred from path shape or Project registry membership alone.

## Goals

- Add existing-session Git worktree creation through the existing Register Project flow.
- Show Git repository folders with a Git folder icon in the folder picker.
- Let users choose between direct existing Project registration and Git worktree creation from the
  selected Git repository folder.
- Reuse the existing `create_git_worktree` TurnAction and action execution lifecycle for worktree
  creation.
- Keep operation progress, failure, retry, and discard in the chat timeline action card.
- Refresh Project surfaces when the action completes so the created worktree appears as a registered
  Project.
- Support removing an Azents-owned worktree from the session and, when explicitly selected, deleting
  the underlying worktree through ownership-based cleanup.
- Preserve the existing safety boundary: ordinary registered Projects are never filesystem-deleted by
  Project registry removal.

## Non-Goals

- Do not add a separate `New worktree` button in the Project panel.
- Do not add a new public backend endpoint such as `/sessions/{session_id}/git-worktrees` for creation.
- Do not expose `create_git_worktree` as a normal slash action in the ChatInput composer.
- Do not model ordinary existing Project registration as a TurnAction in this feature.
- Do not infer filesystem deletion authority from path prefixes, folder names, or Project rows alone.
- Do not implement force-delete for dirty worktrees in the initial delivery.
- Do not redesign the full Project provisioning/import lifecycle.

## Current Behavior

The current Project panel supports listing session Projects, registering an existing folder as a
Project, handling Project registration requests, and removing Project registry rows. Registering a
folder calls the existing Project registration API and does not modify the filesystem.

The current worktree substrate already contains the required operation model:

- `CreateGitWorktreeAction` is a `TurnAction` with `source_project_path` and `starting_ref`.
- Existing session input writes accept `ChatAction` payloads and store TurnActions as `action_message`
  input buffers.
- The worker promotes action input buffers to durable transcript events, runs operation TurnActions
  before model dispatch, records durable action execution state/events, and broadcasts
  `action_execution_updated` projections.
- A successful worktree action registers the created worktree path as a session Project and creates a
  context invalidation boundary before later model turns use updated Project context.

The frontend does not yet expose this existing-session worktree action from the Project panel. The
Register Project picker does not yet identify Git repository directories, and Project deletion does
not yet offer a separate cleanup option for Azents-owned worktree Projects.

## Proposed Design

### Unified Register Project entry point

The Project panel keeps the existing Register Project button as the only entry point for adding
Projects. There is no separate New Worktree button.

When the picker lists folders, Git repositories are rendered with a Git folder icon. The backend
supplies a lightweight repository metadata projection on directory entries, for example
`repository_type: "git" | null`. The frontend uses this metadata only for display and interaction
branching. Detailed Git refs are still loaded by the existing Git ref preview endpoint when the user
chooses worktree mode.

For ordinary folders, selecting Register keeps the existing direct Project registration flow.

For Git repository folders, selecting Register opens a modal before any write occurs.

### Git repository registration modal

The modal contains a `Registration type` select dropdown with two options:

- `Existing project` — register the selected folder directly as a Project.
- `Git worktree` — create an Azents-owned worktree from the selected repository and add that worktree
  as a Project.

The default selection is `Existing project`. Worktree creation is an explicit opt-in because it
creates a new branch-backed worktree operation rather than simply adding the selected folder.

In `Existing project` mode, the modal shows concise explanatory copy and the submit button is
`Register`. Submitting calls the existing Project registration API.

In `Git worktree` mode, the modal shows a base ref selector using the existing Git ref preview query.
The submit button is `Create worktree`. Submitting enqueues a `create_git_worktree` TurnAction for the
current session.

### Frontend action enqueue contract

The Project panel gets a dedicated tRPC mutation for the worktree creation intent. This mutation is a
frontend wrapper only; it does not correspond to a new backend worktree route. Internally it calls the
existing chat input write API with:

```json
{
  "message": "",
  "action": {
    "type": "create_git_worktree",
    "source_project_path": "/workspace/agent/repo",
    "starting_ref": "refs/heads/main"
  }
}
```

This keeps the Project panel UX separate from the general ChatInput composer while preserving the
backend action-as-operation contract. The composer slash action list does not expose a parameterized
`create_git_worktree` action.

### Progress, completion, and failure display

The chat timeline action card is the single source of truth for worktree operation progress. The
Project panel does not duplicate running rows or retry/discard controls.

After successful submit, the modal closes and the Project panel shows a lightweight notice or toast
that worktree creation has started and progress is available in the chat timeline.

On `action_execution_updated` completion for a `create_git_worktree` operation, the frontend
invalidates Project-related queries so the newly registered Project appears without a manual refresh:

- `listAgentProjects`
- `getSessionProjectBrowserManifest`
- `listInputActions` when Project-local Skills may have changed

On failure, the timeline action card shows failure details and existing Retry/Discard controls. The
Project panel does not show a separate failed worktree row.

### Repository metadata projection

Directory entries returned for the Register Project picker include a lightweight repository metadata
field. The initial scope only needs to distinguish Git repositories from ordinary folders.

The backend determines Git repository status for directory entries by checking the directory itself,
including normal `.git` directories and Git worktree `.git` file forms. The projection does not
include branch lists, remote state, dirty status, or commit information. Those details remain owned by
Git ref preview and future cleanup validation flows.

The metadata is a UI projection and does not grant cleanup authority. Cleanup authority always comes
from `session_git_worktrees` ownership metadata.

### Removing Projects and deleting worktrees

Project removal has two levels:

1. **Remove from session** — delete only the `session_workspace_projects` registry row. This is
   available for all Projects and remains the default action.
2. **Delete worktree** — remove the Azents-owned worktree filesystem/branch side effects through the
   worktree cleanup lifecycle. This is available only when the Project is linked to a
   `session_git_worktrees` ownership row.

For ordinary registered Projects, filesystem deletion is never offered from Project removal. For
Azents-owned worktree Projects, the confirmation modal exposes both choices. Deleting the worktree is
separate, destructive, and requires explicit confirmation.

The initial delivery blocks cleanup when the worktree has uncommitted changes. Force delete is left to
a later design. Cleanup failures are surfaced as cleanup failures; they do not rewrite the original
creation action as successful or failed.

## API and Data Model Changes

### Public API

No new public worktree creation endpoint is added. Worktree creation uses the existing chat input
write endpoint with a `create_git_worktree` action payload.

Directory entry response schemas need a lightweight repository metadata field for folder listings.
The public clients must be regenerated from OpenAPI after this schema changes.

Worktree deletion may require an explicit ownership-based cleanup endpoint or an extension of the
existing cleanup API so the UI can target a specific Azents-owned worktree Project. The endpoint must
validate session access, Project ownership linkage, and cleanup safety. It must not accept arbitrary
paths as deletion authority.

### Frontend tRPC

Add a Project-panel-specific tRPC mutation for worktree creation. It wraps the existing generated
`chatV1CreateInput` call and accepts a typed input with:

- `agentId`
- `sessionId`
- `sourceProjectPath`
- `startingRef`
- generated `clientRequestId`

The existing Project registration mutation remains unchanged for `Existing project` mode.

### Data model

The creation path reuses existing action execution and session worktree ownership tables. The design
assumes worktree allocations are linked to registered session Projects through ownership metadata such
as `session_workspace_project_id`.

If specific worktree deletion requires additional cleanup state, it belongs to the worktree ownership
model rather than the Project registry row.

## Runtime and Lifecycle Behavior

Worktree creation is executed by the existing worker action processing path:

1. Project panel enqueues a `create_git_worktree` action input.
2. The worker promotes it into a durable `action_message` event.
3. The worker executes the operation before later model dispatch.
4. Durable action execution events record progress and logs.
5. On success, the created worktree path is registered as a session Project.
6. Project mutation triggers the existing context invalidation boundary before later model turns.
7. The frontend refreshes Project surfaces after action completion.

If the action fails, later pending input remains behind the failed operation until the user retries or
discards it through the timeline action card.

## Error Handling

- Registering a selected folder directly uses the existing Project registration error mapping.
- Git ref preview errors are shown inside the registration modal when `Git worktree` mode is selected.
- Missing or invalid base ref blocks `Create worktree` submission.
- Worktree action execution failures are durable action execution failures and are shown in the
  timeline action card.
- Project panel worktree creation submit failures show a lightweight submit error and do not create a
  fake Project row.
- Cleanup is blocked for uncommitted worktrees in the initial delivery.
- Cleanup target not found, ownership mismatch, or access denial returns safe not-found/access errors.

## Security and Permissions

- Existing session access checks remain workspace membership and active session checks.
- Source paths remain normalized under the Agent Workspace root and cannot be path traversal targets.
- Git repository metadata projection is display-only and does not authorize deletion.
- Destructive worktree deletion is authorized only by explicit `session_git_worktrees` ownership
  linkage to the selected session Project.
- Ordinary registered Projects cannot be filesystem-deleted through this feature.
- The action payload includes workspace paths and refs and is visible only through session-authorized
  APIs/projections.

## Rollout Plan

Ship as stacked PRs:

1. Design document.
2. Implementation plan with validation matrix and fixture prerequisites.
3. Backend/API contract for repository metadata projection and existing-session worktree action
   acceptance tests.
4. Frontend Project panel registration modal and worktree action wrapper.
5. Ownership-based worktree delete/cleanup UX and backend cleanup contract.
6. Validation report, including commands, environment, and implementation/spec comparison.
7. Spec promotion for workspace and chat execution flows.
8. Cleanup of stale implementation plan artifacts.

## Alternatives Considered

### Add a separate New Worktree button

Rejected. It splits Project addition into two entry points and makes users decide before browsing the
folder hierarchy. The Register Project flow already represents the user's intent to add workspace
context to the session.

### Create a new backend `/git-worktrees` attach API

Rejected. ADR-0094 established operation TurnActions as the session operation model. A separate
creation endpoint would reintroduce a parallel worktree operation lifecycle and weaken timeline
progress/retry/discard consistency.

### Detect Git repositories by calling Git ref preview for every folder in the frontend

Rejected. It creates N+1 runtime operations, slower folder rendering, ambiguous error handling, and
unnecessary load. A lightweight backend directory-entry projection is a better fit for list rendering.

### Show pending/running worktree rows in Project panel

Rejected for the initial delivery. The timeline action card is already the durable action progress
surface with logs, failure, retry, and discard. Duplicating operation state in the Project panel would
increase synchronization complexity.

### Delete filesystem state whenever a worktree Project row is removed

Rejected. Removing a Project row is not destructive today and must remain safe for ordinary Projects.
Filesystem deletion must be an explicit Azents-owned worktree cleanup action.

## Test Strategy

### E2E primary verification matrix

Product behavior should be verified with browser E2E when a runtime Git fixture is available.
Required scenarios:

| Scenario | Expected evidence |
| --- | --- |
| Git repository folder rendering | Register Project picker shows ordinary folders with folder icons and Git repositories with Git folder icons. |
| Direct registration from Git folder | Git repository registration modal defaults to `Existing project`; submitting registers the selected folder directly. |
| Worktree mode base ref selection | Selecting `Git worktree` loads base refs and requires a selected starting ref. |
| Existing-session worktree creation | Submitting worktree mode closes the modal, shows a lightweight started notice, and adds an action execution card to the chat timeline. |
| Completion refresh | After action completion, the created worktree appears in the Project list and Project browser manifest without manual refresh. |
| Failure and recovery | Invalid ref or Git failure shows failure in the timeline action card with Retry and Discard, not as a fake Project row. |
| Remove from session | Removing any Project deletes only the registry row and leaves filesystem state intact. |
| Delete Azents-owned worktree | Worktree Project exposes a separate delete option that uses ownership-based cleanup and removes the worktree when clean. |
| Dirty worktree cleanup block | Worktree delete is blocked when uncommitted changes exist; force delete is not offered. |

### E2E plan

- Use a runtime fixture with an Agent Workspace containing at least one ordinary directory and one Git
  repository.
- Use the Project panel Register Project flow to browse and select folders.
- Capture DOM assertions for icon differences and registration modal mode switching.
- Drive worktree creation and wait for the timeline action card to complete.
- Assert Project list and Project browser manifest refresh after completion.
- Drive remove-only and delete-worktree confirmation flows.

### Fixture and prerequisite support

Runtime-backed E2E requires:

- a ready Agent Runtime with file listing and Git runner operations enabled;
- a Git repository under `/workspace/agent` with at least one local branch;
- a valid base ref for successful worktree creation;
- an invalid ref or controlled Git failure for recovery testing;
- a clean worktree cleanup case; and
- a dirty worktree cleanup case for the deletion block.

If this fixture is unavailable in CI, browser E2E can be optional for the validation PR only when
backend/API/service tests and Storybook states cover the same contracts and the validation report
records the fixture gap explicitly.

### Backend tests

- API test that existing-session input write accepts `create_git_worktree` and creates an action input
  buffer.
- Service or API tests for repository metadata projection on directory entries.
- Cleanup tests proving worktree deletion requires ownership linkage and does not apply to ordinary
  Project rows.
- Cleanup tests for dirty-worktree blocking and safe failure reporting.

### Frontend tests and stories

- Storybook states for ordinary folder entries and Git folder entries.
- Storybook states for the Git registration modal in `Existing project` and `Git worktree` modes.
- Storybook states for base ref loading, loaded, empty, and error states.
- Storybook states for Azents-owned worktree Project removal choices.
- TypeScript quality checks validate the tRPC wrapper and generated client usage.

### Static and quality checks

Implementation PRs must run applicable checks:

- TypeScript: `pnpm run format`, `pnpm run lint`, `pnpm run typecheck`, `pnpm run build` from
  `typescript/`.
- Backend: targeted `pytest`, `ruff`, `pyright`, and OpenAPI/client generation when schema changes.
- Documentation: `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`.
