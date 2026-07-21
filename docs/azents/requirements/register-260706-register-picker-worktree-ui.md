---
title: "Register Project Picker Worktree UI Historical Requirements Reconstruction"
created: 2026-07-06
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: register-260706
historical_reconstruction: true
migration_source: "docs/azents/adr/0095-register-project-picker-worktree-ui.md"
---

# Register Project Picker Worktree UI Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `register-260706`
- Source: `docs/azents/adr/register-260706-register-picker-worktree-ui.md`
- Historical source date basis: `2026-07-06`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[action-260705/ADR](../adr/action-260705-action-as-operation-turn-actions.md) models Git worktree creation as a `create_git_worktree` operation TurnAction. The UI still
needs a clear entrypoint for choosing the source folder and deciding whether to register that folder
as-is or create an Azents-owned worktree from it.

The existing Workspace browser has a Project-first surface. Its `Projects` mode shows already
registered Project roots and Project-root actions. That surface must not redefine the Register
Project picker as a list of already registered Projects. Register Project is an add flow: it must let
users browse the Agent Workspace and choose a folder candidate.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
