---
title: "New Session Mixed Workspace Selection Implementation Plan"
created: 2026-07-05
updated: 2026-07-05
tags: [plan, backend, frontend, api, session, workspace, git]
---

# New Session Mixed Workspace Selection Implementation Plan

## Feature Summary

Implement the design in `docs/azents/design/new-session-mixed-workspace-selection.md` and ADR-0093.
New-session creation becomes an ordered workspace item list that can mix existing Project items and
Git Worktree items. The azents-web draft selector keeps one compact `Add workspace` flow and renders
compact selected rows for explicit Project and Worktree items.

## Stack Prefix

`New session mixed workspace selection`

## PR Boundaries

The current branch is already scoped to correcting the new-session/worktree behavior. To keep the
active fix reviewable, ship as one integrated correction PR rather than a long new stack, but keep the
internal work phases below explicit in the PR body and commits.

If this needs to be split later, use these boundaries:

1. Design and implementation plan.
2. Backend API/data model/service/initialization support.
3. Frontend compact selector and generated client integration.
4. Spec promotion and validation cleanup.

## Phase 1 — Design and Plan

- Add ADR-0093 for the accepted mixed workspace decisions.
- Add final design document with test strategy.
- Add this implementation plan.

## Phase 2 — Backend Contract and Defaults

- Add workspace item request/response models.
- Add `workspace_items` to direct-session and first-message create APIs.
- Keep legacy `project_paths` / `workspace_mode` conversion during transition.
- Add `agent_project_defaults.item_type` and remove unique `(agent_id, path)` default constraint.
- Store default item intent as ordered `(path, item_type)` rows.
- Return item-level defaults from the defaults API.
- Normalize reusable presets to original/source Project paths.

## Phase 3 — Backend Session Creation and Initialization

- Convert workspace item list into:
  - direct existing Project registrations;
  - worktree initialization allocation groups.
- Create one `SessionInitialization` for all selected Worktree items.
- Create one `session_git_worktrees` allocation and step group per Worktree item.
- Update initialization runner to process all worktree allocations in step order.
- Mark initialization ready only after all blocking worktree setup is complete.
- Preserve cleanup behavior that already iterates allocations.

## Phase 4 — Frontend Compact Selector

- Remove the global workspace mode segmented control.
- Keep one compact `Add workspace` menu/picker flow.
- Render selected workspace rows compactly.
- Show branch controls only for Worktree rows.
- Keep full path in popover only.
- Use Git refs preview for Worktree ref selection and capability/errors.
- Filter Worktree base branch choices to local branches only; exclude remote branches from the default selector.
- Send `workspaceItems` to tRPC/API.

## Phase 5 — OpenAPI, Clients, Tests, Specs

- Dump public/admin OpenAPI specs.
- Regenerate Python and TypeScript public clients.
- Run backend service/API tests for session creation and worktree initialization.
- Run frontend format/lint/typecheck/build.
- Update living specs after implementation validation.

## Validation Matrix

| Area | Required checks |
| --- | --- |
| Existing Project only | API/service creates exact Project rows and ready initialization. |
| Single Worktree | API/service creates one allocation and first-run gate remains. |
| Multiple Worktrees | Initialization runner processes all allocations in sequence. |
| Mixed Project + Worktree | Direct Project rows and generated Worktree Project rows coexist. |
| Defaults | Worktree defaults persist as source Project + Worktree item type. |
| Presets | Quick-select presets contain original/source paths only. |
| UI | Compact selected rows, path popover, one additive workspace menu. |
| Generated clients | No manual edits under generated client directories. |

## Known Blockers / Prerequisites

- Runtime-dependent E2E may be blocked locally if the runtime has no Docker socket. If blocked, record
  the failure and rely on API/service/static checks plus CI for runtime-backed coverage.
- Git ref dynamic default restoration depends on runner Git preview availability. The API/design
  should support the item type first; UI can resolve refs through existing preview state.

## Spec Impact Candidates

- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/domain/workspace.md`

Update after implementation validation to describe `workspace_items`, mixed setup, defaults, and
compact selector behavior.
