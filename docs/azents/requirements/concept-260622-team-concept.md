---
title: "Remove Workspace Team Concept Historical Requirements Reconstruction"
created: 2026-06-22
implemented: 2026-06-22
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: concept-260622
historical_reconstruction: true
migration_source: "docs/azents/design/remove-workspace-team-concept.md"
---

# Remove Workspace Team Concept Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `concept-260622`
- Source: `docs/azents/design/concept-260622-team-concept.md`
- Historical source date basis: `2026-06-22`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Workspace currently has an optional Team hierarchy and TeamMember membership model. The product no longer needs workspace sub-teams. WorkspaceUser is sufficient for membership, role, and permission boundaries.

The current Team concept affects these areas:

- Admin API routes:
  - `/team/v1/**`
  - `/team-member/v1/**`
- Backend model/repository/service packages:
  - `rdb/models/team.py`
  - `rdb/models/team_member.py`
  - `repos/team/**`
  - `repos/team_member/**`
  - `services/team/**`
  - `services/team_member/**`
- Permissions and roles:
  - `Resource.TEAMS`, `Resource.TEAM_MEMBERS`
  - `Permissions.TEAMS_*`, `Permissions.TEAM_MEMBERS_*`
- Toolkit visibility:
  - `ToolkitScopeType` currently supports `workspace` and `team`.
  - `ToolkitRepository.list_available_for_workspace_user()` joins `TeamMember` to include team-scoped toolkits.
- Public Toolkit API/UI:
  - Toolkit scope create/read models expose `scope_type` and `scope_id`.
  - azents-web Toolkit scope UI allows choosing team/workspace.
- Testenv/E2E:
  - Admin Team CRUD tests.
  - Admin TeamMember CRUD tests.
  - Public Toolkit team-scope test cases.
- Living specs:
  - `docs/azents/spec/domain/workspace.md`
  - `docs/azents/spec/domain/toolkit.md`

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
