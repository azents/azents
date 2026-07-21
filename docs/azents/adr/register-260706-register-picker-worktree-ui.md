---
title: "Register Project Picker Worktree UI"
created: 2026-07-06
tags: [architecture, frontend, workspace, git, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: register-260706
historical_reconstruction: true
migration_source: "docs/azents/adr/0095-register-project-picker-worktree-ui.md"
---

# register-260706/ADR: Register Project Picker Worktree UI

## Context

[action-260705/ADR](./action-260705-action-as-operation-turn-actions.md) models Git worktree creation as a `create_git_worktree` operation TurnAction. The UI still
needs a clear entrypoint for choosing the source folder and deciding whether to register that folder
as-is or create an Azents-owned worktree from it.

The existing Workspace browser has a Project-first surface. Its `Projects` mode shows already
registered Project roots and Project-root actions. That surface must not redefine the Register
Project picker as a list of already registered Projects. Register Project is an add flow: it must let
users browse the Agent Workspace and choose a folder candidate.

## Decision

### register-260706/ADR-D1 — Register Project remains the only existing-session Project-addition entrypoint

Existing sessions do not get a separate `New worktree` button. Users start both direct Project
registration and worktree creation from the existing Register Project button.

### register-260706/ADR-D2 — Register Project opens an Agent Workspace folder picker

Clicking Register Project opens a runtime-backed folder picker rooted at the Agent Workspace root.
The picker lists folders from the Agent Workspace filesystem, not the existing session Project set.

The Project browser manifest may still render the Workspace panel's `Projects` mode, but it must not
be used as the Register Project picker fallback data source.

### register-260706/ADR-D3 — Git repository folders are visually identified in the picker

Folders that the backend identifies as Git repositories render with a Git folder icon in the Register
Project picker. Non-Git folders use the normal folder icon.

### register-260706/ADR-D4 — Selecting a Git folder opens the registration mode dialog

Selecting a non-Git folder immediately registers it as an existing Project.

Selecting a Git repository folder opens a registration dialog instead of immediately registering it.
The dialog offers a dropdown with the same conceptual choices as the new-session project selector:

- register the selected folder as an existing Project; or
- create a new worktree from the selected Git repository.

### register-260706/ADR-D5 — Worktree mode requires a base ref

When the dialog is in worktree mode, users must choose a base Git ref before submitting. The frontend
uses Git ref preview for the selected source repository and sends the chosen ref in the
`create_git_worktree` action payload.

## Consequences

- Register Project is a full Agent Workspace browse flow, not a Project root re-selection flow.
- The Workspace browser's Project-first mode remains separate from the Project-addition picker.
- Existing-session worktree creation uses the same user decision shape as new-session worktree
  selection while keeping one Project-addition entrypoint.
- The frontend must keep Project browser manifest entries out of the Register Project picker data
  source, except for backend-provided repository metadata that is part of actual folder entries.

## Alternatives

### Add a separate New worktree button

Rejected. It splits the Project-addition entrypoint and makes users decide the operation before they
choose the source folder.

### Show registered Projects in the Register Project picker

Rejected. Registered Projects are already present in the Workspace browser's `Projects` mode. The
Register Project picker is for adding a new Project candidate from the Agent Workspace filesystem.

### Immediately create a worktree whenever a Git folder is selected

Rejected. Users must be able to register a Git repository folder directly or create a new worktree
from it. The registration mode dialog preserves that choice.

## Migration provenance

- Historical source filename: `0095-register-project-picker-worktree-ui.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
