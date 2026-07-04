---
title: "ADR-0093: New Session Mixed Workspace Selection"
created: 2026-07-05
tags: [architecture, product, backend, frontend, session, workspace, git]
---

# ADR-0093: New Session Mixed Workspace Selection

## Context

ADR-0086 established explicit new-session Project selection: the selected Project UI equals the
Project bindings created for the new session, and reusable Project presets are convenience paths rather
than canonical Project identities.

ADR-0091 introduced a durable session initialization lifecycle that gates first-run dispatch while
startup work is pending. ADR-0092 introduced Azents-owned Git worktrees as session-owned generated
Projects with explicit ownership and cleanup metadata.

The first implemented worktree UI split new-session setup into a global workspace mode:

- `existing_projects`: multiple existing Project paths;
- `git_worktree`: one source Project and one starting ref.

That global mode is not the intended product model. Users need to assemble a new session workspace as
a list of items, where normal Projects and Git worktree requests can be mixed in one session. The UI
must preserve the existing compact Project selector flow instead of introducing a separate Project
selection screen.

## Decision

### ADR-0093-D1 — New-session workspace input is an ordered item list

New-session creation uses an ordered workspace item list rather than a global `existing_projects` vs
`git_worktree` mode.

Each item is one of:

- existing Project item: an existing Agent Workspace Project path to register directly on the created
  session;
- Git worktree item: a source/original Project path plus Worktree mode metadata that asks Azents to
  create an owned worktree before first-run dispatch.

A single new session may include any mix of existing Project items and Git worktree items, including
multiple Git worktree items.

### ADR-0093-D2 — Existing Project and Worktree are additive item actions

The new-session selector exposes one compact `Add workspace` entrypoint with item actions for adding
an existing Project or adding a Git Worktree from a source Project. Both actions can use recent
Project presets or the same directory picker surface with an explicit purpose.

Selected rows are explicit workspace items, not a session-wide mode switch. An existing Project row
may offer a shortcut to add a Worktree from the same source path, but converting the whole selector
between Project and Worktree modes is not part of the model.

This keeps source selection and materialization intent clear:

1. choose whether the next item is an existing Project or a Worktree request;
2. choose the source Project path for that item;
3. for Worktree items, choose the local starting branch.

### ADR-0093-D3 — New-session selector stays compact and follows the existing UI flow

The compact `Add workspace` button/menu remains in the selector. The UI must not add a second
standalone Project selection section below the selected list.

Selected workspace items render as compact rows:

- basename as the primary label;
- item type badge (`Project` or `Worktree`);
- Worktree branch control only for Worktree rows;
- remove action close to the row;
- no full path inline.

Full paths remain available through the same hover/touch popover pattern used by the current Project
chips. Worktree rows may show a compact local branch selector; remote branches and tags stay out of
the default selector. More detailed Worktree settings belong in a popover, menu, or bottom sheet
instead of expanding each item into a large card.

### ADR-0093-D4 — Default selected workspace comes from the last created session configuration

The new-session selector initializes from the workspace configuration used when the latest created
non-primary session was created.

If that configuration included a worktree item, the default is restored as:

- the source/original Project path;
- a Worktree item for that source path;
- a dynamically resolved starting ref from the current local branch/default of the source Project.

Worktree base branch selection shows local branches only. Remote branches are excluded from the default selector; tags and other refs can be introduced later through a separate advanced flow if needed.

The concrete generated worktree path from the prior session is not reused as the default selection.

This supersedes path-only default restoration where necessary: defaults must preserve enough creation
intent to distinguish an existing Project item from a Worktree-mode source Project item.

### ADR-0093-D5 — Quick-select presets contain only original/source Projects

The quick-select Project preset list shows original/source Projects only.

Generated worktree paths are ephemeral and must not appear as reusable quick-select Projects. When a
worktree-created Project is observed by default/preset update logic, it is normalized back to its
source/original Project before being stored or shown as a quick-select candidate.

Worktree-created Projects may still be written to the Agent Project Catalog for current-session
Project Browser visibility as required by ADR-0092, but they do not become reusable new-session
presets/default source paths.

### ADR-0093-D6 — Session initialization processes all worktree items before first run

For a mixed workspace item list, existing Project items are registered directly during session
creation. Worktree items create `session_git_worktrees` allocation rows and ordered initialization
steps. First-run dispatch remains gated by the single session initialization lifecycle until all
blocking Worktree setup and registration steps are ready.

Worktree processing may be sequential within the one session initialization lifecycle. A failure in a
blocking worktree setup step keeps the first input pending and exposes the existing initialization
retry/recovery path.

### ADR-0093-D7 — Worktree identity and cleanup remain separate from Project rows

ADR-0092 remains authoritative: `session_workspace_projects` is only the prompt/tool Project scope,
and `session_git_worktrees` is the ownership and cleanup authority.

A Worktree item eventually registers the generated worktree path as a session Project only after Git
setup succeeds. Cleanup deletes only resources backed by explicit `session_git_worktrees` ownership
rows.

## Consequences

- The public new-session API contract must evolve from a binary mode union to an item-list contract.
- Generated OpenAPI clients must be regenerated after the API schema changes.
- Existing Project-only creation remains representable as a list containing only existing Project
  items.
- Existing single-worktree creation remains representable as a list containing one Worktree item.
- The backend must preserve creation-time workspace intent for future default restoration, because
  current session Project rows alone cannot distinguish a directly selected Project from a generated
  worktree Project.
- The UI should update the existing compact selector instead of introducing a separate Project picker
  surface.
- Preset/default update logic must normalize generated worktree paths to source/original Project
  paths where reusable new-session selection is involved.

## Alternatives

### Keep global workspace mode and add a multi-worktree mode

Rejected. It still makes the user choose a global mode and does not model the intended per-Project
choice.

### Add a second standalone Project selection section

Rejected. A second selector below the current surface makes the draft composer heavier and separates
controls from the selected item list. The compact selector should keep one additive entrypoint.

### Restore previous worktree paths as future defaults

Rejected. Worktree paths are ephemeral generated session resources. Reusing them as defaults would
leak old session materialization into new sessions and conflict with cleanup semantics.

### Store generated worktree paths in quick-select presets

Rejected. Quick-select presets are for reusable original/source Projects. Worktree paths may appear in
current-session browser/catalog projections, but not as reusable new-session candidates.

## Implementation Notes

The likely implementation shape is:

- introduce workspace item request/response models;
- create a creation-time workspace configuration snapshot or equivalent data source for defaults;
- normalize old path-only defaults into existing Project items;
- restore Worktree defaults from source/original Project plus dynamic current local ref;
- create existing Project rows for Project items during session creation;
- create one `session_git_worktrees` allocation and step group per Worktree item;
- update initialization execution to process multiple allocations in step order;
- update azents-web `NewSessionProjectSelector` to compact selected rows and one `Add workspace`
  menu for existing Project and Worktree item actions;
- keep the directory picker as the shared source path picker for both item actions;
- regenerate public OpenAPI clients and update tests.

## Test Strategy

E2E remains the primary product verification path.

Required coverage:

- Project-only new session creates exactly selected Project rows.
- One Worktree item creates one owned worktree, registers the generated Project after setup, and gates
  the first run until ready.
- Multiple Worktree items in one session are initialized before first-run dispatch.
- Mixed existing Project + Worktree items create direct Project rows and generated worktree Project
  rows in the same session.
- Latest-session defaults restore Worktree items as source/original Project rows with Worktree mode,
  not generated worktree paths.
- Quick-select presets show only original/source Project paths after worktree usage.
- Compact mobile selector renders selected rows without full paths inline, exposes full path through
  popover, and keeps branch controls only on Worktree rows.

Supporting checks:

- backend service tests for item-list normalization, default restoration, preset normalization, and
  multiple worktree initialization;
- API tests for first-message and direct session creation with mixed item lists;
- frontend typecheck/lint/build and component coverage for compact selector states;
- OpenAPI/client generation checks after schema changes.
