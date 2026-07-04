---
title: "New Session Mixed Workspace Selection Design"
created: 2026-07-05
updated: 2026-07-05
tags: [product, backend, frontend, api, session, workspace, git]
---

# New Session Mixed Workspace Selection Design

## Overview

Azents new-session setup must let users compose the workspace for a new non-primary
AgentSession as a compact ordered list of items. A session can include existing Project paths,
Azents-owned Git worktrees, or both.

The current implemented model is a global workspace mode: either existing Projects or one Git
worktree. That model blocks the intended workflow because Worktree is an additive workspace item type,
not a session-wide mode.

This design supersedes the global-mode UX for new-session creation while preserving the decisions in:

- ADR-0086: new-session Project selection is explicit and exact;
- ADR-0091: blocking startup work uses SessionInitialization and gates first-run dispatch;
- ADR-0092: Azents-owned Git worktree ownership and cleanup live in `session_git_worktrees`;
- ADR-0093: new-session mixed workspace selection and compact UI policy.

## Problem

Users need to start a new session with combinations such as:

- existing Project only;
- one Git worktree only;
- multiple Git worktrees;
- existing Project plus one or more Git worktrees;
- a repeated source Git Project where one item is direct Project mode and another item is Worktree mode.

The current global mode cannot express this. It also pushes Worktree selection into the wrong mental
model: users should build a list of concrete workspace items, where each item is either a direct
existing Project or a Worktree request from a source Project.

## Goals

- Replace global new-session workspace mode with an ordered workspace item list.
- Allow existing Project and Git worktree items to coexist in one session creation request.
- Allow multiple Worktree items in one session.
- Keep one compact `Add workspace` menu/picker flow.
- Show Worktree branch controls only on Worktree rows.
- Keep the mobile selector compact: one selected item per row, no inline full path.
- Restore defaults from the latest created session's creation-time workspace configuration.
- Restore previous Worktree items as source/original Project + Worktree mode, not generated worktree paths.
- Keep quick-select presets limited to reusable original/source Projects.
- Keep worktree ownership and cleanup authority separate from Project rows.

## Non-Goals

- Do not reintroduce existing-session worktree attach or multi-worktree registration.
- Do not turn the Agent Project Catalog into worktree ownership state.
- Do not store generated worktree paths as reusable new-session presets/defaults.
- Do not add a separate Project selection section under the current selector.
- Do not reintroduce a global Project-vs-Worktree mode toggle.
- Do not make Project rows store Git metadata or cleanup authority.
- Do not implement custom runner scripts or non-typed Git operations.

## Current Behavior

Backend currently accepts these shapes for new-session creation:

- legacy `project_paths` / `existing_projects` mode for direct Project registrations;
- `git_worktree` mode for one source Project and starting ref.

`ChatSessionService.create_team_session()` and
`AgentSessionInputService.create_team_session_with_buffered_input()` branch on that union. Existing
Projects receive ready no-op initialization, while Git worktree mode creates one worktree allocation
and one initialization step group.

`SessionGitWorktreeService.run_git_worktree_initialization()` currently rejects multiple allocation
rows in a single session.

The draft UI currently has a global selector between existing Projects and new worktree. That control
must be replaced with an additive item list.

## Proposed Design

### Workspace item contract

New-session creation accepts an ordered item list:

```json
{
  "workspace_items": [
    {
      "type": "existing_project",
      "path": "/workspace/agent/home"
    },
    {
      "type": "git_worktree",
      "source_project_path": "/workspace/agent/azents",
      "starting_ref": "refs/heads/main"
    }
  ]
}
```

Existing `project_paths` and the old `workspace_mode` union may be translated internally during the
migration window, but azents-web should move to `workspace_items` as the primary contract.

Rules:

- `existing_project.path` is normalized with the existing Project path policy.
- `git_worktree.source_project_path` is normalized with the same Agent Workspace path policy.
- `git_worktree.starting_ref` is required and trimmed.
- exact duplicate existing Project paths are deduplicated preserving order;
- Worktree items are not deduplicated solely by source path, because multiple worktrees from one
  source Project are valid;
- an existing Project item and a Worktree item may reference the same source path.

### Session creation lifecycle

During new-session creation:

1. Create the `AgentSession`.
2. Register all existing Project items directly as `session_workspace_projects`.
3. Upsert original/source Project paths into quick-select presets:
   - existing Project item uses `path`;
   - Git worktree item uses `source_project_path`.
4. Persist creation-time default workspace item intent for the Agent.
5. If there are no Worktree items, create or ensure ready no-op initialization.
6. If Worktree items exist, create one `SessionInitialization` and one step group per Worktree item.
7. Store one `session_git_worktrees` allocation row per Worktree item.
8. Enqueue the first input buffer as usual.
9. Worker initialization gate prevents first-run dispatch until all blocking Worktree setup is ready.

### Multiple worktree initialization

`SessionGitWorktreeService` processes allocation step groups ordered by initialization step sequence.
A blocking failure in any group fails the session initialization and leaves pending input buffers
pending. Retry uses the existing initialization retry path and resets failed/downstream steps.

The final initialization becomes `ready` only after every Worktree item has completed:

- Git worktree creation;
- generated Project registration;
- Project catalog upsert;
- non-blocking status refresh completed or warned.

### Defaults and presets

Defaults must represent creation-time intent, not only resulting session Project rows.

Default item storage must distinguish:

- existing Project item;
- Git Worktree item restored from the source/original Project.

When a prior session used a Worktree item, the next new-session page restores:

- source/original Project path;
- Worktree selected on that row;
- starting ref resolved dynamically from the current source Project local/default branch.

The concrete generated worktree path is not restored.

Quick-select presets show only original/source Projects. If a worktree-created Project path is seen by
preset/default logic, it is normalized back to its recorded `session_git_worktrees.source_project_path`
before becoming reusable selection data.

### API response for defaults

The new-session defaults API should return item-level defaults rather than only path strings:

```json
{
  "items": [
    {
      "type": "existing_project",
      "path": "/workspace/agent/home"
    },
    {
      "type": "git_worktree",
      "source_project_path": "/workspace/agent/azents",
      "starting_ref": null
    }
  ],
  "source": {
    "type": "last_created_session"
  }
}
```

A compatibility `project_paths` field may remain for old clients, derived from existing Project items
only or from original/source paths, but azents-web should use `items`.

### UI design

The current Project selector surface stays in place. The global mode selector is removed.

Compact selected-row layout:

```text
Workspaces                                    [Add workspace]
Choose projects and worktrees for this session.

azents                         Project        [Add worktree]  [remove]
api                            Worktree       branch: main ▾  [remove]
docs                           Project                         [remove]
```

Rules:

- `Add workspace` is the single entrypoint for adding existing Project items and Worktree items.
- The same directory picker can be opened with an explicit purpose: existing Project or Worktree
  source Project.
- Selected rows are explicit item rows, not rows with a mode toggle.
- Existing Project rows may offer a shortcut to add a Worktree item from the same source path.
- Worktree rows show a compact local branch selector.
- Full path is not shown inline; it remains in the hover/touch popover.
- Remove stays close to the affected row.
- Detailed Worktree options use popover/menu/bottom sheet instead of expanding the row into a large
  card.

### Git branch preview

The UI uses Git refs preview for Worktree rows. The default branch selector shows only local branches
(`type = "branch"`). Remote branches, tags, and other refs can be added later through a separate
advanced flow. Preview loading, empty, and error states affect only Worktree item readiness and do not
block Project-only session creation.

### Cleanup and ownership

Worktree cleanup remains unchanged in principle:

- generated worktree path is registered as a session Project only after setup succeeds;
- `session_git_worktrees` is the cleanup authority;
- archive/delete cleanup iterates all non-cleaned allocations for the session;
- generated worktree Project rows and catalog entries do not become reusable new-session defaults.

## Data Model Changes

### `agent_project_defaults`

Extend default rows to store item type:

```text
agent_project_defaults
- id
- agent_id
- path
- item_type: existing_project | git_worktree
- position
- created_at
- updated_at
```

`path` stores:

- existing Project path for `existing_project`;
- source/original Project path for `git_worktree`.

The unique `(agent_id, path)` constraint must be removed because the same source path may appear once
as direct Project and once as Worktree. The unique `(agent_id, position)` constraint remains.

### `session_git_worktrees`

No ownership model change is required. The existing 1:N session relationship supports multiple
allocations. The initialization runner must stop assuming exactly one allocation.

## API Changes

### Request schemas

Add:

- `ExistingProjectWorkspaceItemRequest`
- `GitWorktreeWorkspaceItemRequest`
- `AgentSessionWorkspaceItemRequest`

Add `workspace_items` to:

- `POST /chat/v1/agents/{agent_id}/sessions`
- `POST /chat/v1/agents/{agent_id}/sessions/messages`

Migration behavior:

- If `workspace_items` is provided, it is authoritative.
- Else if legacy `workspace_mode` is provided, convert it to item list.
- Else if legacy `project_paths` is provided, convert it to existing Project items.
- Else reject as invalid for explicit new-session creation.

### Defaults response

Extend `GET /chat/v1/agents/{agent_id}/session-project-defaults` to return item defaults.

### Git refs preview

Keep `GET /chat/v1/agents/{agent_id}/git-refs?source_project_path=...`. The compact UI uses it for
Worktree rows and default ref resolution. The base branch selector filters this preview to local
branches only (`type = "branch"`). Remote branches, tags, and other refs are not shown in the default
Worktree base branch selector.

## Error Handling

- Invalid Project paths fail request validation with existing `InvalidProjectPath` handling.
- Empty Worktree starting ref fails request validation.
- Git refs preview failure should not break direct Project mode.
- Worktree creation failure fails initialization and leaves first input pending.
- Multiple Worktree initialization fails fast on the first blocking failed allocation.
- Retry uses the existing initialization retry/reset flow.

## Security and Permissions

- Session creation keeps existing Agent/workspace membership checks.
- Source Project paths must remain under the Agent Workspace policy.
- Runner Git operations remain typed operations and must not become backend shell strings.
- Cleanup still requires explicit `session_git_worktrees` ownership rows.
- Full paths may be shown only to users who can access the Agent/session creation surface.

## Migration and Rollout

1. Add ADR-0093 and this design document.
2. Add `agent_project_default_item_type` enum and `agent_project_defaults.item_type`.
3. Remove the unique `(agent_id, path)` default constraint.
4. Backfill existing default rows as `existing_project`.
5. Add backend workspace item domain/input conversion.
6. Update session creation services to create existing rows and multiple Worktree allocations from
   one item list.
7. Update initialization runner to process all allocations in sequence.
8. Update defaults/presets to store original/source Project paths.
9. Update REST schemas and regenerate OpenAPI/public clients.
10. Update azents-web draft selector to compact row UI.
11. Update specs after implementation validation.

## Alternatives Considered

### Keep global mode and add a third mixed mode

Rejected. It keeps mode selection as the top-level mental model and still hides the per-selected-Git
Project choice.

### Add a second standalone Project selection section

Rejected. A second selector below the current surface makes the draft composer heavier and separates
controls from the selected item list. The compact selector should keep one additive entrypoint.

### Derive defaults from current session Project rows only

Rejected. Resulting rows cannot distinguish a direct Project from a generated Worktree Project. The
selector needs creation-time item intent.

### Store generated worktree paths in presets/defaults

Rejected. Generated worktree paths are ephemeral session resources and conflict with cleanup and
future-session ergonomics.

## Validation Evidence

Repository inspection confirmed:

- ADR-0086 already requires explicit new-session Project selection and path presets.
- ADR-0091 already provides the first-run initialization gate.
- ADR-0092 already separates Worktree ownership from Project rows.
- `session_git_worktrees` has already been migrated away from one-row-per-session uniqueness.
- Cleanup paths already iterate multiple allocations.
- The current runner initialization path still enforces one allocation and must be updated.
- The current UI component uses a global `SegmentedControl`, which must be removed.

## Test Strategy

E2E is the primary product behavior verification path. Backend service/API tests and frontend static
checks are required supporting gates.

### E2E primary verification matrix

| Scenario | Expected result |
| --- | --- |
| Existing Project only | New session has exactly selected existing Project rows and ready initialization. |
| Single Worktree item | Initialization creates one worktree, registers generated Project, then first run starts. |
| Multiple Worktree items | All worktree allocations complete before first run starts. |
| Mixed existing Project + Worktree | Direct Project rows and generated worktree Project rows coexist in the created session. |
| Same source Project direct + Worktree | One direct source Project row and one generated worktree Project row are created. |
| Worktree failure | Initialization fails, first input remains pending, retry action remains available. |
| Defaults restore Worktree intent | New-session page restores source Project + Worktree mode, not prior generated worktree path. |
| Preset normalization | Quick-select list contains original/source Projects only after worktree usage. |
| Compact mobile selector | Selected rows are compact, full path is popover-only, branch controls appear only on Worktree rows. |

### E2E plan

Use the existing testenv/browser harness where available:

1. seed user, workspace, Agent, team-primary session;
2. create source Git repository fixtures under `/workspace/agent`;
3. create new sessions through the browser first-message path;
4. observe initialization live state until ready/failure;
5. read session Project API responses to confirm resulting rows;
6. reopen `/sessions/new` to verify defaults and presets;
7. capture DOM assertions or screenshots for compact selector states.

### Fixture and seed requirements

- Authenticated workspace member.
- Agent with runtime capable of Git typed runner operations.
- Source Git repository with at least one local branch and one alternate ref.
- Optional fixture for invalid ref and branch/path collision behavior.
- Prior session with Worktree item for default restoration tests.

### Credential/prerequisite snapshot

No external credentials are required. Evidence should include runtime provider mode, Git version when
available, source Project path, selected refs, created session id, and generated worktree allocation
ids. Do not include runtime-control tokens or credentials.

### CI execution policy

- Backend service/API tests are required in normal CI.
- TypeScript format/lint/typecheck/build are required for azents-web changes.
- Browser E2E should run in the existing E2E lane when runner prerequisites are available.
- Runtime-dependent Git E2E may be optional/live only if CI cannot provide Docker/runner access; API
  and unit coverage must still run.

### Skip/fail criteria

- Missing Docker socket or runner fixture may skip runtime-dependent E2E with explicit evidence.
- API tests for workspace item normalization, defaults, presets, and multiple allocation creation must
  not be skipped.
- Frontend compact selector typecheck/lint/build must not be skipped.

### Supporting test checklist

- Service tests for `workspace_items` conversion from legacy modes.
- Service tests for existing + worktree mixed creation.
- Service tests for multiple worktree allocation step groups.
- Repository tests for `agent_project_defaults.item_type` and duplicate path with different item type.
- API tests for new request/response schema.
- Frontend component/story coverage for empty, loading, error, Project row, Worktree row, and mobile
  overflow states.
