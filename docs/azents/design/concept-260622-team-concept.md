---
title: "Remove Workspace Team Concept"
created: 2026-06-22
updated: 2026-06-22
implemented: 2026-06-22
tags: [backend, api, frontend, documentation, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: concept-260622
migration_source: "docs/azents/design/remove-workspace-team-concept.md"
historical_reconstruction: true
---

# Remove Workspace Team Concept

## Context

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

## Decision

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

## Data Migration

Migration steps:

1. Delete `toolkit_scopes` rows where `scope_type = 'team'`.
2. Drop `team_members`.
3. Drop `teams`.
4. Drop `team_member_role` enum.
5. Remove `team` from `toolkit_scope_type` enum if PostgreSQL supports the migration path in the generated revision. If enum value removal is not safe in the deployed PostgreSQL path, leave the DB enum value in place and constrain application code to workspace-only. The code-level API must not expose team.

## API Contract Changes

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

## Frontend Impact

- Remove Toolkit scope type selector and scope ID input.
- Display scopes as workspace visibility only.
- Remove team-specific labels from azents-web messages.
- Regenerate OpenAPI clients and adapt tRPC/router usage.

## Test Strategy

Primary verification is backend unit/API tests and deterministic E2E updates.

- Remove Team/TeamMember admin E2E tests because the routes no longer exist.
- Remove/replace Toolkit team-scope E2E cases with workspace-only scope checks.
- Run azents Python tests.
- Run azents E2E deterministic tests where Docker is available. In this runtime, E2E may be blocked by missing Docker socket; if blocked, rely on CI for E2E evidence.
- Regenerate OpenAPI specs and TypeScript clients, then run TypeScript typecheck/lint for affected packages.

## Risks

- Existing database rows with team-scoped ToolkitScope must be cleaned before Team tables are dropped.
- Generated clients may still expose removed admin routes until OpenAPI/client regeneration is complete.
- Historical migration files still mention teams; do not rewrite old migration history.
