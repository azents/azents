---
title: "Session Workspace Project Existing Folder Registration Historical Decision Reconstruction"
created: 2026-06-11
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: existing-260611
historical_reconstruction: true
migration_source: "docs/azents/design/session-workspace-project-existing-folder-registration.md"
---

# Session Workspace Project Existing Folder Registration Historical Decision Reconstruction

- Snapshot: `existing-260611`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/session-workspace-project-existing-folder-registration.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### existing-260611/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Decision

Reduce MVP Project surface to **existing folder registration**.

- Project is a registry entry where user explicitly registered a directory that already exists inside Agent Workspace.
- Public UI/API and DB/service/runtime layers do not include Project Source, archive upload, empty folder bootstrap, or load state.
- Project registration API does not change filesystem. It checks that Runtime is active and target path is an actual directory, then creates registry row.
- Project delete API removes only registry row. It does not delete filesystem folder.
- Agent registration request approve/reject remains. Flow where a folder created by Agent is included into Project through user approval matches boundary registration model.
- Project Source / provisioning / Runtime pending load ACK are removed from current implementation and separated into future Project Import or Project Provisioning design.

### Explicit source section: Public API Contract

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

### Explicit source section: Frontend Contract

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

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
