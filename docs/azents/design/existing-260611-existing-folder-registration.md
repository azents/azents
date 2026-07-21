---
title: "Session Workspace Project Existing Folder Registration"
created: 2026-06-11
updated: 2026-06-11
implemented: 2026-06-11
tags: [backend, api, frontend, documentation, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: existing-260611
migration_source: "docs/azents/design/session-workspace-project-existing-folder-registration.md"
historical_reconstruction: true
---

# Session Workspace Project Existing Folder Registration

## Context

The existing Session Workspace Project design included Project boundary registry and Project Source-based provisioning in the same MVP scope. As a result, Project Source archive upload, empty folder bootstrap, `loaded=false` pending load, Runtime Runner pull/ACK, source object lifecycle, and loading/failed UI state were all needed at once.

The core thing the product needs now is to explicitly mark a specific folder inside Agent Workspace as Project boundary. Project boundary is used for project-scoped `AGENTS.md`, future skill discovery, and registered project guidance in prompt. Provisioning such as file creation, archive extract, and git clone is separate from this boundary problem.

## Decision

Reduce MVP Project surface to **existing folder registration**.

- Project is a registry entry where user explicitly registered a directory that already exists inside Agent Workspace.
- Public UI/API and DB/service/runtime layers do not include Project Source, archive upload, empty folder bootstrap, or load state.
- Project registration API does not change filesystem. It checks that Runtime is active and target path is an actual directory, then creates registry row.
- Project delete API removes only registry row. It does not delete filesystem folder.
- Agent registration request approve/reject remains. Flow where a folder created by Agent is included into Project through user approval matches boundary registration model.
- Project Source / provisioning / Runtime pending load ACK are removed from current implementation and separated into future Project Import or Project Provisioning design.

## Public API Contract

Keep:

- `GET /chat/v1/agents/{agent_id}/sessions/{session_id}/projects`
- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/register`
- `DELETE /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/{project_id}`
- `GET /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests`
- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests/{request_id}/approve`
- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests/{request_id}/reject`

Remove:

- `GET /chat/v1/agents/{agent_id}/project-sources`
- `POST /chat/v1/agents/{agent_id}/project-sources/archive`
- `DELETE /chat/v1/project-sources/{source_id}`
- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/bootstrap`

New register request body:

```json
{
  "path": "/workspace/agent/my-project"
}
```

Project does not have separate name. The specified path itself is Project boundary.

## Frontend Contract

Workspace panel Projects tab exposes only:

- Registered Projects list
- existing folder registration form
- registration request approve/reject list

Remove these UI elements:

- Project Source list
- archive upload
- source delete
- source type selection
- empty folder/archive bootstrap form
- loading/failed Project state

## Implementation Notes

This change reduces public surface and removes DB/service/repository/runtime provisioning dead code. Drop existing Project Source table and load-state columns by migration, and remove Runtime pending load helper to simplify Project registry into existing folder boundary registry.

New `register_existing_folder_for_session` service flow:

1. Verify user can access the selected AgentSession.
2. Look up AgentRuntime.
3. Verify path is actual runtime directory through Runner operation.
4. Validate Project path policy.
5. Create Project registry row.

Both response schema and internal DB model do not include source/load fields and represent only Project boundary.

## Test Strategy

### E2E Primary

- In fixture where Agent Workspace is READY, create `/workspace/agent/example` directory.
- Call `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/register`, then verify `GET /projects` returns registered Project with only `id/name/path/created_at/updated_at`.
- Deleting registered Project removes it from list and keeps filesystem folder.
- Registering non-existing folder or root/nested path returns 400/409-class error.

### Unit / Integration

- Keep existing service-level path validation tests.
- Add register existing folder service tests for directory validation, default name, conflict behavior.
- Use OpenAPI generated client typecheck to verify no usage remains for removed source/bootstrap endpoints.

### Manual QA

- Verify Workspace panel Projects tab does not show source upload/bootstrap UI.
- Register existing folder path and verify list updates immediately.
- Verify registration request approve/reject UI still works.
