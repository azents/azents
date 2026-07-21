---
title: "TeamMember CRUD Document Historical Decision Reconstruction"
created: 2026-02-13
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: team-260213
historical_reconstruction: true
migration_source: "docs/azents/design/team-member-crud.md"
---

# TeamMember CRUD Document Historical Decision Reconstruction

- Snapshot: `team-260213`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/team-member-crud.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### team-260213/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Design Decisions

| Item | Decision | Rationale |
|------|------|------|
| role type | PostgreSQL ENUM (`team_member_role`) | Enforce valid values at DB level |
| role values | `owner`, `manager`, `member` | Reflect requested role system |
| prevent duplicate membership | UNIQUE(team_id, workspace_user_id) | Prevent duplicate joins to same Team |
| referential integrity | FK `team_id`, `workspace_user_id` + CASCADE | Clean up membership when Team/WorkspaceUser is deleted |
| workspace match validation | Team.workspace_id == WorkspaceUser.workspace_id | Prevent cross-workspace membership |
| permission policy | Not implemented | Provide API/schema first; permissions implemented later |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
