---
title: "ADR-0070: Remove Workspace Team Concept"
created: 2026-06-22
tags: [backend, api, frontend]
---

# ADR-0070: Remove Workspace Team Concept

## Context

Azents Workspaces currently include optional Team and TeamMember entities. Team was intended as a sub-workspace grouping and as a Toolkit visibility target. In practice, WorkspaceUser already owns the active membership/permission model and Team adds API, database, frontend, and generated-client surface without a current product need.

## Decision

Remove Team and TeamMember as product/domain concepts.

### ADR-0070-D1 — WorkspaceUser is the only Workspace membership model

Workspace membership and role decisions are represented by WorkspaceUser only. Team-specific membership and role state is removed.

### ADR-0070-D2 — Toolkit visibility is workspace-only

ToolkitScope remains as a Toolkit-to-Workspace visibility row, but team-scoped Toolkit visibility is removed. Runtime availability checks no longer join TeamMember; enabled workspace-scoped toolkits are available to workspace members.

### ADR-0070-D3 — Remove Team/TeamMember API and generated clients

Admin Team and TeamMember routes are removed. OpenAPI specs and generated clients must be regenerated so clients do not retain removed route contracts.

## Consequences

- Existing team-scoped toolkit scopes are deleted by migration.
- Existing Team and TeamMember data is dropped.
- The UI no longer provides Team scope controls.
- Historical migrations and historical ADR/design documents may still mention teams as history. Current specs must not describe Team as current behavior.
