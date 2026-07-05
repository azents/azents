---
title: "Session Operation Turn Action Migration Implementation Plan"
created: 2026-07-05
updated: 2026-07-05
tags: [plan, backend, frontend, api, session, workspace, git]
---

# Session Operation Turn Action Migration Implementation Plan

## Feature Summary

Implement ADR-0094 and the design in
`docs/azents/design/session-operation-turn-action-migration.md`.

This feature is a prerequisite for a later product feature: adding a Git worktree to an
already-existing session. The follow-up existing-session add-worktree UI/API is intentionally not part
of this stack. This stack migrates the operation substrate from `SessionInitialization` to
`create_git_worktree` TurnActions so both new-session setup and the later existing-session workflow can
share one ordered action execution model.

## Stack Prefix

`Session operation TurnAction migration`

## Planned PR Stack

1. **Session operation TurnAction migration [1/9]: Design**
   - Add ADR-0094.
   - Add final design document.
2. **Session operation TurnAction migration [2/9]: Implementation plan**
   - Add this implementation plan.
   - Define stack boundaries, validation matrix, fixture prerequisites, spec impact, rollout, and
     cleanup notes.
3. **Session operation TurnAction migration [3/9]: Action contract and durable execution model**
   - Add `create_git_worktree` TurnAction schema.
   - Add durable action execution state/events or equivalent durable event records keyed by
     `action_message` event identity.
   - Add repository/service projection primitives for live state reconstruction.
   - Remove initialization request identity from the target model.
4. **Session operation TurnAction migration [4/9]: Runner action execution and context boundary**
   - Process `create_git_worktree` TurnAction in the session runner loop.
   - Execute typed Runner Git worktree operations from action payload.
   - Register created worktree paths as session Projects on success.
   - Refresh catalog and Skill projection.
   - Stop the current processing boundary and enqueue follow-up wake-up after Project mutation.
5. **Session operation TurnAction migration [5/9]: New-session clean migration**
   - Replace new-session worktree setup fields with ordered action setup input.
   - Remove legacy `workspace_items`, `workspace_mode`, `project_paths`, and initialization
     compatibility behavior.
   - Regenerate OpenAPI clients.
   - Update azents-web draft-session request mapping to send worktree setup as TurnAction input.
6. **Session operation TurnAction migration [6/9]: Retry, discard, and action progress UI**
   - Add retry/discard APIs and service behavior for failed action execution.
   - Add live/timeline rendering for action execution progress.
   - Add UI states for running, failed, retrying, failed-final, warning, and completed.
7. **Session operation TurnAction migration [7/9]: Validation and E2E fixtures**
   - Add deterministic E2E/testenv fixture support for Git worktree action execution.
   - Run planned E2E matrix and record evidence.
   - Fix discovered implementation issues.
8. **Session operation TurnAction migration [8/9]: Spec promotion**
   - Run spec review.
   - Update current specs under `docs/azents/spec/**`.
   - Mark design implemented only after the feature is complete and verified.
9. **Session operation TurnAction migration [9/9]: Cleanup**
   - Remove stale implementation plan documents after specs are current.
   - Remove obsolete initialization-only docs or references that are no longer current behavior.

## Phase Dependencies

- Phase 3 must land before runner and frontend phases because it defines public action/execution
  contracts.
- Phase 4 depends on Phase 3 durable action execution primitives.
- Phase 5 depends on Phase 4 because new-session worktree setup must have an executable action path.
- Phase 6 depends on Phase 3 projection primitives and Phase 4 failure semantics.
- Phase 7 validates the integrated stack after API, runner, and UI phases exist.
- Phase 8 must happen after validation so living specs describe implemented behavior.
- Phase 9 happens only after spec promotion and merge readiness.

## Data, API, and Runtime Changes by Phase

### Phase 3 — Action contract and durable execution model

- Extend `ChatAction` / `TurnAction` with `create_git_worktree`.
- Define durable action execution state/events associated with `action_message` event identity.
- Define projection query APIs used by `/live` and action detail views.
- Migrate `session_git_worktrees` linkage away from `initialization_id` / initialization step IDs to
  action execution identity.
- Add database migrations using Alembic revision tooling.

### Phase 4 — Runner execution

- Teach input-buffer promotion / session runner action processing to treat `create_git_worktree` as
  executable action work.
- Execute Git worktree creation with typed Runner operations.
- Register created worktree Project and update catalog.
- Sync Skill projection after Project registration.
- Add context invalidation result so the runner stops current processing and enqueues follow-up
  wake-up when pending work remains.

### Phase 5 — New-session clean migration

- Replace new-session worktree setup request flow with ordered setup action input.
- Remove old initialization request fields and frontend compatibility paths.
- Regenerate Python and TypeScript public clients from OpenAPI.
- Update draft-session frontend container and selector request mapping.

### Phase 6 — Retry/discard and UI

- Add retry/discard write operations keyed by failed action execution identity.
- Implement `failed_final` semantics.
- Render action execution projection in chat timeline/live state.
- Add Workspace/draft UI integration points for retry/discard state visibility.

## E2E Primary Validation Matrix

| Scenario | Phase | Expected result |
| --- | --- | --- |
| New session with one worktree action | 7 | Worktree action completes before first model run; generated Project appears. |
| New session worktree action followed by first user message | 7 | Follow-up wake-up rebuilds fresh context before first model run. |
| Worktree Git failure | 7 | Action fails, later pending input remains pending, Retry/Discard shown. |
| Retry failed action | 7 | Only the failed action retries; ordering is preserved. |
| Discard failed action | 7 | Failed action records `failed_final`; later pending input can proceed. |
| Browser reconnect during action execution | 7 | Live projection recovers from durable action execution state/events. |
| Worker restart during action execution | 7 | Action identity is preserved and execution resumes or fails durably. |
| Project mutation context boundary | 7 | Model-visible context includes newly registered worktree Project after follow-up wake-up. |

## Fixture and Prerequisite Support

E2E and backend integration tests need deterministic Git/runtime fixtures:

- a ready runtime with typed Runner Git operations enabled;
- a Git repository under `/workspace/agent` with at least one local branch;
- an invalid ref/collision fixture for failure tests;
- cleanup support for created worktrees and branches; and
- a way to observe Project registry and action execution projection through public APIs.

If existing E2E fixtures cannot provide reliable Git operation control, add testenv fixture support in
Phase 7 rather than weakening the product assertions.

## Test Strategy by Phase

### Phase 3

- Migration tests for new action execution tables/events.
- Repository tests for action execution projection and event ordering.
- Schema tests for `create_git_worktree` action validation.
- OpenAPI generation check after API contract changes.

### Phase 4

- Service tests for successful worktree action execution.
- Failure tests for runtime unavailable, invalid ref, Git command failure, and Project registration
  failure.
- Tests that Project mutation returns a context invalidation/follow-up wake-up result.
- Tests that Skill projection sync is requested after Project registration.

### Phase 5

- API route tests for new-session setup action input.
- Removal tests or static checks to ensure legacy workspace setup request fields are gone.
- Frontend container tests or Storybook fixtures for draft selector request mapping.
- Generated client regeneration verification.

### Phase 6

- Retry/discard state transition tests.
- UI stories for running, failed, failed-final, completed, warning, and reconnect-restored action
  execution cards.
- TypeScript format, lint, typecheck, and build checks.

### Phase 7

- Full E2E matrix from this plan.
- Evidence report with commands, screenshots/traces, API snapshots, and cleanup observations.

## Spec Impact Candidates

Likely specs to update in Phase 8:

- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/domain/workspace.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/chat-session-resync.md`
- `docs/azents/spec/flow/run-resume.md`

Expected changes:

- remove `SessionInitialization` as current setup lifecycle;
- describe action-as-operation TurnAction execution;
- describe durable action execution projection in `/live` and detail endpoints;
- describe retry/discard semantics;
- describe context invalidation after Project mutation; and
- describe new-session setup action ordering.

## Rollout and Cleanup Notes

- Ship as a stack because the migration touches API contracts, DB state, worker loop behavior,
  frontend live projection, and E2E fixtures.
- Do not keep legacy API compatibility. Update all first-party frontend and tests in the same stack.
- Regenerate API clients after public contract changes.
- Mark the design implemented only after Phase 7 validation and Phase 8 spec promotion.
- Remove this implementation plan in the cleanup PR once specs are current.

## Known Blockers

No external blocker is known at design time. Implementation may uncover fixture gaps for deterministic
Runner Git operation failure injection; those should be addressed in Phase 7 fixture work.
