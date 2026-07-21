---
title: "Team CRUD Document Historical Requirements Reconstruction"
created: 2026-02-12
implemented: 2026-02-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: team-260212
historical_reconstruction: true
migration_source: "docs/azents/design/team-crud.md"
---

# Team CRUD Document Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `team-260212`
- Source: `docs/azents/design/team-260212-team-crud.md`
- Historical source date basis: `2026-02-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

This is Team CRUD API for managing hierarchical team structure within Workspace (up to 3 levels). It is implemented based on Team entity definition in [core-260207-core-concepts.md](../design/core-260207-core-concepts.md).

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

| Constraint | Name | Description |
|------|------|------|
| UNIQUE | `uq_teams_workspace_slug` | slug uniqueness within Workspace |
| CHECK | `chk_teams_depth` | depth range 1~3 |
| FK CASCADE | `workspace_id → workspaces.id` | delete teams when Workspace is deleted |
| FK CASCADE | `parent_team_id → teams.id` | delete child teams when parent team is deleted |

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
