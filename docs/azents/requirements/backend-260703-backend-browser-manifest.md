---
title: "Backend Project Browser Manifest Historical Requirements Reconstruction"
created: 2026-07-03
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: backend-260703
historical_reconstruction: true
migration_source: "docs/azents/adr/0090-backend-project-browser-manifest.md"
---

# Backend Project Browser Manifest Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `backend-260703`
- Source: `docs/azents/adr/backend-260703-backend-browser-manifest.md`
- Historical source date basis: `2026-07-03`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[browser-260703/ADR](../adr/browser-260703-browser-surface.md) moves the session Workspace browser toward a Project-first surface. It decides that `Projects` is the default browser mode, `All files` remains available as an explicit secondary mode, Project management moves into the Workspace panel, Project root nodes expose registry actions instead of filesystem destructive actions, empty Projects do not fall back to the Agent Workspace root, and the legacy Projects route is normalized away.

The initial design direction considered frontend synthesis of Project-root browser entries from separate Project and workspace API responses. Further design discussion changed this direction. Project manifests are needed not only after an `AgentSession` exists, but also before session creation:

- the new-session composer already has selected Project paths before `session_workspace_projects` rows exist;
- session creation uses `project_paths` as an exact bootstrap set;
- future worktree creation from another session needs to expose newly created workspace paths as reusable Project candidates before a target session exists;
- frontend-only synthesis would duplicate Project root action policy, filesystem status interpretation, and bootstrap semantics across existing-session, pre-session, and future worktree flows.

Therefore the backend should own the Project browser manifest contract and expose reusable Project-set manifest construction.

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
