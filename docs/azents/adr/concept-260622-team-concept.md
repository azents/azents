---
title: "Remove Workspace Team Concept Historical Decision Reconstruction"
created: 2026-06-22
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: concept-260622
historical_reconstruction: true
migration_source: "docs/azents/design/remove-workspace-team-concept.md"
---

# Remove Workspace Team Concept Historical Decision Reconstruction

- Snapshot: `concept-260622`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/remove-workspace-team-concept.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### concept-260622/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Decision

Remove Workspace Team as a product/domain concept.

1. Delete Team and TeamMember backend API, service, repository, models, tests, and E2E coverage.
2. Remove Team/TeamMember permissions from the role permission matrix.
3. Make Toolkit scope workspace-only.
   - Existing ToolkitScope table remains as the association that records workspace-level Toolkit visibility.
   - `scope_type` remains for this migration phase, but the code-level enum only exposes `workspace`.
   - Team-scoped rows are deleted during migration before removing the `team` enum value.
4. Remove team scope creation from public Toolkit API/UI.
   - Scope create requests no longer accept client-supplied `scope_type` / `scope_id`.
   - Server creates workspace scope only.
   - Existing default workspace scope creation on Toolkit create remains.
5. Remove stale ShellEnvironment Team-scope spec text. The current code no longer has ShellEnvironment scope models.

### Explicit source section: API Contract Changes

Removed admin routes:

- `/team/v1/teams`
- `/team/v1/workspaces/{handle}/teams`
- `/team/v1/teams/{team_id}`
- `/team-member/v1/team-members`
- `/team-member/v1/teams/{team_id}/team-members`
- `/team-member/v1/team-members/{team_member_id}`

Changed public Toolkit route:

- `POST /toolkit/v1/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/scopes`
  - Before: request body selected `scope_type` and `scope_id`.
  - After: request body is empty or omitted; server creates workspace scope for the current workspace.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
