---
title: "Model Session Operations as Turn Actions Historical Requirements Reconstruction"
created: 2026-07-05
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: action-260705
historical_reconstruction: true
migration_source: "docs/azents/adr/0094-action-as-operation-turn-actions.md"
---

# Model Session Operations as Turn Actions Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `action-260705`
- Source: `docs/azents/adr/action-260705-action-as-operation-turn-actions.md`
- Historical source date basis: `2026-07-05`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[initialization-260703/ADR](../adr/initialization-260703-initialization-lifecycle.md) introduced `SessionInitialization` as a one-to-one setup lifecycle for an
`AgentSession`. It solved the first Git worktree use case by gating the first run while setup work
created an Azents-owned Git worktree and registered the created path as a session Project.

That model is too narrow for the next product direction: users must be able to add a Git worktree to
an already-existing session. That flow is not session initialization. It is a user-requested turn that
changes the session Project set before later model turns use the updated workspace context.

The same prerequisite also affects new-session worktree setup. New-session setup should not remain a
separate initialization-only path while existing-session worktree setup uses a different operation
model. The migration target is a clean action-as-operation architecture that covers both:

- new-session setup actions that must run before the first user message reaches the model; and
- existing-session workspace mutation actions that must run in ordered turn context before later
  pending input is processed.

Compatibility with the current `workspace_items`, `workspace_mode`, `project_paths`, and
`SessionInitialization` request model is intentionally out of scope. This is a clean migration.

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
