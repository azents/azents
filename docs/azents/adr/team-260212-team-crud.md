---
title: "Team CRUD Document Historical Decision Reconstruction"
created: 2026-02-12
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: team-260212
historical_reconstruction: true
migration_source: "docs/azents/design/team-crud.md"
---

# Team CRUD Document Historical Decision Reconstruction

- Snapshot: `team-260212`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/team-crud.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### team-260212/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Design Decisions

| Item | Decision | Rationale |
|------|------|------|
| depth calculation | automatically calculated from parent_team_id | Prevent user input errors and ensure consistency |
| slug unique scope | unique within Workspace | Collision needs to be prevented only inside same organization |
| deletion strategy | CASCADE | Prevent child teams from becoming orphaned |
| list query | workspace_id required | Listing all teams is meaningless; Workspace context always needed |
| parent validation | check Workspace match too | Prevent accidental parent assignment to team from another Workspace |

### Explicit source section: Constraints

| Constraint | Name | Description |
|------|------|------|
| UNIQUE | `uq_teams_workspace_slug` | slug uniqueness within Workspace |
| CHECK | `chk_teams_depth` | depth range 1~3 |
| FK CASCADE | `workspace_id → workspaces.id` | delete teams when Workspace is deleted |
| FK CASCADE | `parent_team_id → teams.id` | delete child teams when parent team is deleted |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
