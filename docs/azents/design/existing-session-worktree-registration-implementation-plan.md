---
title: "Existing Session Worktree Registration Implementation Plan"
created: 2026-07-05
updated: 2026-07-05
tags: [backend, frontend, api, session, workspace, git, plan]
---

# Existing Session Worktree Registration Implementation Plan

## Feature Summary

This plan implements [Existing Session Worktree Registration](existing-session-worktree-registration.md).
The feature lets users add Azents-owned Git worktree Projects to an existing AgentSession through the
existing Register Project flow. It keeps worktree creation on the `create_git_worktree` operation
TurnAction path and keeps timeline action cards as the durable progress/retry/discard surface.

## Stack Prefix

`Existing-session worktree registration`

## Planned PR Stack

| PR | Title | Scope |
| --- | --- | --- |
| 1 | `Existing-session worktree registration [1/8]: Design` | Approved design document. |
| 2 | `Existing-session worktree registration [2/8]: Implementation plan` | This multi-phase plan, validation matrix, fixture needs, and rollout boundaries. |
| 3 | `Existing-session worktree registration [3/8]: Repository metadata contract` | Backend/API schema for lightweight Git repository metadata on directory entries, OpenAPI/client regeneration, and backend tests. |
| 4 | `Existing-session worktree registration [4/8]: Project registration worktree flow` | Frontend Register Project modal modes, Project-panel worktree action tRPC wrapper, Git ref selection, started notice, and Storybook states. |
| 5 | `Existing-session worktree registration [5/8]: Worktree cleanup choices` | Ownership-based remove-only vs delete-worktree UX and backend cleanup target contract/tests. |
| 6 | `Existing-session worktree registration [6/8]: Validation` | Run planned checks, record environment/evidence, compare implementation against specs, and fix validation bugs. |
| 7 | `Existing-session worktree registration [7/8]: Spec promotion` | Run spec review and update living specs for shipped behavior. |
| 8 | `Existing-session worktree registration [8/8]: Cleanup` | Remove this implementation plan and stale temporary artifacts after specs are current. |

## Dependencies Between Phases

- PR 3 depends on PR 2 because the API/schema scope is defined by this plan.
- PR 4 depends on PR 3 because frontend Git folder icons and types need generated repository metadata.
- PR 5 depends on PR 3 for ownership metadata in Project entries and cleanup API contract; it can be
  developed after or alongside PR 4 but should be reviewed later because it adds destructive cleanup
  semantics.
- PR 6 depends on PRs 3-5 being implemented.
- PR 7 depends on validation findings from PR 6.
- PR 8 depends on PR 7 so the living specs become the current source of truth before plan cleanup.

## Phase Details

### PR 3 — Repository metadata contract

Backend/API/runtime scope:

- Add lightweight repository metadata to workspace directory entry responses, initially
  `repository_type: "git" | null` or an equivalent generated-client-friendly object.
- Detect Git repositories for directory entries shown in the Register Project picker, including normal
  `.git` directories and worktree `.git` file forms.
- Keep Git ref lists, dirty state, and branch information out of this projection.
- Regenerate OpenAPI and generated public clients.
- Add tests for Git repository metadata projection.
- Add backend API contract coverage that an existing session input write can accept
  `create_git_worktree` as an action input. This protects the Project-panel wrapper path even though
  creation uses an existing backend route.

Out of scope:

- Frontend modal UX.
- Worktree cleanup/delete semantics.
- Living spec promotion, except if a schema change cannot be reviewed without local contract notes.

### PR 4 — Project registration worktree flow

Frontend scope:

- Keep Register Project as the only Project-addition entry point.
- Render Git repository folders with a Git folder icon using the metadata from PR 3.
- For Git repository folders, open a registration modal with a `Registration type` select.
- Default the modal to `Existing project`.
- In `Existing project` mode, call the existing Project registration mutation.
- In `Git worktree` mode, preview Git refs, require a base ref, and call a Project-panel-specific tRPC
  wrapper that internally uses `chatV1CreateInput` with `create_git_worktree`.
- Do not expose `create_git_worktree` in ChatInput slash action selection.
- Show a lightweight started notice after successful submit.
- Invalidate Project queries and input actions on completed `create_git_worktree` action execution.
- Add Storybook states for ordinary folders, Git folders, modal modes, and Git ref loading/loaded/error.

Out of scope:

- Destructive worktree cleanup choices.
- Backend repository metadata implementation.

### PR 5 — Worktree cleanup choices

Backend/API/frontend scope:

- Preserve remove-only Project behavior for all Projects.
- Expose a separate delete-worktree option only for Projects linked to Azents-owned worktree ownership
  rows.
- Add or adapt a cleanup endpoint that targets a specific owned worktree Project/allocation, validates
  session access and ownership linkage, and never accepts arbitrary path authority.
- Block initial delete-worktree cleanup when uncommitted changes are present.
- Leave force delete out of scope.
- Add UI confirmation choices for Azents-owned worktree Projects:
  - remove from session only;
  - delete worktree.
- Add tests for ownership checks, ordinary Project safety, dirty-worktree blocking, and cleanup failure
  handling.

Out of scope:

- Broader workspace cleanup policy.
- Force cleanup of dirty worktrees.

### PR 6 — Validation

Validation scope:

- Run all planned backend and frontend checks available in the local/runtime environment.
- Run runtime-backed browser E2E if the Git fixture is available.
- If browser E2E is not available, document the fixture gap and provide backend/API/Storybook/CI
  evidence for each user-visible contract.
- Compare implementation against current living specs and identify required spec-promotion changes.
- Fix discovered bugs in this PR when they are validation-scoped; otherwise patch the responsible
  phase and rebase downstream branches.

### PR 7 — Spec promotion

Spec scope:

- Run `/spec-review` or equivalent manual spec impact review.
- Update `docs/azents/spec/domain/workspace.md` for:
  - Git repository metadata projection;
  - Register Project modal modes;
  - existing-session worktree creation through operation actions;
  - remove-only vs delete-worktree choices.
- Update `docs/azents/spec/flow/agent-execution-loop.md` for existing-session Project-panel
  `create_git_worktree` action processing and context invalidation.
- Update `docs/azents/spec/flow/chat-session-resync.md` for timeline progress as the source of truth
  and completion-triggered Project refresh expectations.
- Update `last_verified_at` and `spec_version` according to repository spec rules.
- Decide whether a follow-up ADR is needed. The current design appears to implement ADR-0094 rather
  than introduce a new hard-to-reverse architecture decision, so an ADR is not expected unless cleanup
  policy expands.

### PR 8 — Cleanup

Cleanup scope:

- Remove this implementation plan document.
- Regenerate docs index.
- Do not change behavior or specs in this PR.

## Data, API, and Runtime Changes by Phase

| Area | PR 3 | PR 4 | PR 5 | PR 6-8 |
| --- | --- | --- | --- | --- |
| Public API schema | Add repository metadata to directory entries; regenerate clients. | No new backend schema expected. | Add/adapt ownership-based cleanup target if needed; regenerate clients. | Spec docs only after validation. |
| Backend services | Git repository metadata projection; existing-session action acceptance test. | None expected. | Cleanup target validation, ownership checks, dirty-worktree block. | Validation fixes only. |
| Worker/action lifecycle | No behavior change expected; test existing acceptance. | No behavior change. | No creation lifecycle change. | Spec promotion reflects current behavior. |
| Frontend | Type consumption after generated clients. | Register Project modal, tRPC wrapper, notices, invalidation, stories. | Cleanup confirmation choices and stories. | Validation/spec/cleanup docs. |

## Test Strategy by Phase

### PR 3

- Backend unit/service/API tests for repository metadata projection.
- API test for existing-session `create_git_worktree` input acceptance.
- OpenAPI dump and generated public client regeneration.
- Python targeted checks for changed backend modules.

### PR 4

- Storybook states for:
  - ordinary folder entry;
  - Git folder entry;
  - Git registration modal existing-project mode;
  - Git registration modal worktree mode;
  - Git ref loading/loaded/error.
- TypeScript `format`, `lint`, `typecheck`, and `build`.
- Manual browser smoke test when runtime is available.

### PR 5

- Backend tests for ownership-based cleanup and ordinary Project safety.
- Backend tests for dirty-worktree cleanup block.
- Storybook states for remove-only vs delete-worktree choices.
- TypeScript and backend targeted quality checks.

### PR 6

- Full planned check list for code modified by PRs 3-5.
- Optional runtime-backed E2E if fixture is available.
- Validation report with commands, environment, results, gaps, and fixes.

### PR 7

- Documentation validation:
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - `git diff --check`

### PR 8

- Documentation validation after plan cleanup.

## E2E Primary Validation Matrix

| Behavior | Evidence |
| --- | --- |
| Git repository icon | Register Project picker shows Git folders differently from ordinary folders. |
| Direct Git folder registration | Git folder modal defaults to Existing project and registers the selected folder directly. |
| Worktree base ref selection | Worktree mode loads refs and blocks submit until a base ref is selected. |
| Worktree creation enqueue | Submit enqueues a `create_git_worktree` action and shows a timeline action card. |
| Started feedback | Project panel shows lightweight started feedback without duplicating action logs. |
| Completion refresh | Project list and Project browser manifest show the created worktree after action completion. |
| Failure recovery | Failed worktree action appears in the timeline with Retry/Discard controls. |
| Remove-only Project | Removing a Project deletes only the registry row. |
| Delete owned worktree | Owned worktree Project exposes a delete-worktree choice and cleans up a clean worktree. |
| Dirty cleanup block | Dirty owned worktree cleanup is blocked without a force option. |

## Fixture and Prerequisite Requirements

Runtime-backed E2E requires:

- an active Agent Runtime with file listing, Git ref preview, worktree creation, and cleanup operations;
- an ordinary directory under `/workspace/agent`;
- a Git repository under `/workspace/agent` with at least one local branch;
- a clean worktree case for deletion;
- a dirty worktree case for deletion block; and
- a controlled invalid ref or Git failure for recovery testing.

If these prerequisites are unavailable in CI or the local validation runtime, PR 6 must record the gap
and rely on backend/API tests plus frontend Storybook/typecheck evidence for the corresponding
contracts.

## Blockers and External Actions

No product decisions are currently open. The only known prerequisite risk is runtime-backed browser
E2E fixture availability. That risk blocks full browser evidence but does not block backend/API,
frontend Storybook, or CI validation for the implementation phases.

## Spec Impact Candidates

- `docs/azents/spec/domain/workspace.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/chat-session-resync.md`

## Rollout and Cleanup Notes

The implementation should ship behind normal code review without a separate runtime feature flag. The
behavior appears only in the Project panel and only when Git repository metadata is projected for a
folder. If the worktree cleanup endpoint is delayed, creation can still ship with remove-only behavior
only if PR 5 is explicitly split and the design/spec states the temporary limitation.

After validation and spec promotion, this implementation plan is stale and must be removed by the
cleanup PR.
