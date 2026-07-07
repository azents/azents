---
title: "Remove Project Registration Requests"
created: 2026-07-07
updated: 2026-07-07
implemented: 2026-07-07
tags: [backend, frontend, api, documentation]
---

# Remove Project Registration Requests

## Problem and Goals

`session_workspace_project_registration_requests` exists as a database table, ORM model, repository/service surface, public API, generated client surface, and azents-web panel UI. The product concept behind it is not implemented end to end: there is no agent-facing tool, command, or service path that creates a registration request. The only implemented user-facing Project registration flow is direct user registration of an existing Agent Workspace directory, plus Git worktree creation through durable `create_git_worktree` actions.

This change removes the unimplemented Project registration request concept so the current Project model contains only implemented behavior.

Goals:

- Remove the dead `session_workspace_project_registration_requests` storage contract with a forward Alembic migration.
- Remove backend repository, service, enum, and public API code that only serves registration requests.
- Regenerate public API clients after the public API contract changes.
- Remove azents-web registration request UI and tRPC methods.
- Update living specs so they describe current behavior without the request/approval flow.

## Non-goals

- Do not change direct Project registration semantics for existing Agent Workspace directories.
- Do not change Git worktree setup actions, action-execution retry/discard, or worktree cleanup.
- Do not reinterpret existing historical ADRs or implemented design documents as living specs.
- Do not add a replacement agent-initiated Project registration workflow in this change.

## Current Behavior

Investigation found these implemented surfaces:

- Database:
  - Existing migrations create and later migrate `session_workspace_project_registration_requests`.
  - `RDBSessionWorkspaceProjectRegistrationRequest` maps the table and depends on `SessionWorkspaceProjectRegistrationRequestStatus`.
- Backend:
  - `SessionWorkspaceProjectRepository` contains create/get/list/approve/reject helpers for registration requests.
  - `SessionWorkspaceProjectService` exposes list/approve/reject flows.
  - Public chat API exposes list, approve, and reject routes under `/project-registration-requests`.
  - No source code path calls `create_registration_request()`, so rows cannot be created through an implemented product flow.
- Frontend:
  - azents-web queries the list endpoint and renders an approval/rejection section in `ProjectPanel`.
  - The generated public client exposes the request endpoints and response models.
- Specs:
  - `workspace.md` and `conversation.md` describe the registration request flow as current behavior.

## Proposed Design

### API and Product Behavior

Remove Project registration request endpoints from the public API:

- `GET /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests`
- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests/{request_id}/approve`
- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/project-registration-requests/{request_id}/reject`

The remaining Project registration path is direct user-driven registration:

- `POST /chat/v1/agents/{agent_id}/sessions/{session_id}/projects/register`

Git worktree creation remains an action-execution flow, not a Project registration request flow.

### Data Model and Migration

Create a new forward Alembic migration that drops:

1. `session_workspace_project_registration_requests`
2. `session_workspace_project_registration_request_status`

The migration must be generated through `alembic revision`, then reviewed and edited. Existing executed migrations remain immutable.

Downgrade can recreate the removed table and enum to keep migration reversibility, but application code no longer uses the table after upgrade.

### Backend Code

Remove:

- Registration request enum from `azents.core.enums`.
- Registration request SQLAlchemy enum/model from `rdb/models/session_workspace_project.py`.
- Registration request Pydantic repository data models.
- Registration request repository methods.
- Registration request service error types, error union, and list/approve/reject methods.
- Public API response models, imports, and route handlers for request list/approve/reject.

Keep direct Project create/list/delete/register behavior unchanged.

### Frontend Code

Remove:

- tRPC registration request procedures and generated-client imports.
- `registrationRequests`, approve/reject pending state, and callbacks from workspace panel state.
- Registration request section from `ProjectPanel` and stories.
- Unused localized messages for the removed section.

Project management still shows registered Projects and the Register Project flow.

### Specs and Historical Documents

Living specs should remove request/approval flow text and API route entries. Historical ADRs and implemented design documents that mention the removed concept should remain unchanged unless they are unimplemented and still active. They record past design context, not current behavior.

## Runtime or Lifecycle Behavior

No runtime lifecycle change is introduced. Runtime directory existence checks remain part of direct Project registration and Git worktree operations. Removing the request flow does not restart, reset, or mutate runtimes.

## Error Handling

Public 404/409 errors for the removed request endpoints disappear with the endpoints. Direct Project registration keeps existing `400`, `403/404`, and `409` behaviors.

## Security and Permissions

Removing the endpoints reduces public API surface area. Existing membership checks for direct Project registration, Project list/delete, project browser manifest, Git ref preview, and worktree cleanup remain unchanged.

## Migration and Rollout Plan

1. Land backend/frontend code removal and generated client updates in one PR.
2. Apply the new Alembic migration during normal deployment.
3. Existing pending request rows, if any, are intentionally discarded because no implemented product path can create or resolve them.
4. Rollback through Alembic downgrade recreates the table shape, but code rollback is required to re-enable the old API.

## Test Strategy

E2E primary verification matrix:

| Area | Scenario | Expected result |
| --- | --- | --- |
| Workspace Projects UI | Open an existing concrete session Workspace panel | Project list and Register Project controls render without a registration request section. |
| Direct Project registration | Register a real existing directory | Project row is created, Project browser manifest refreshes, no request approval step appears. |
| Project deletion | Remove a session Project | Registry row is removed without deleting filesystem contents. |
| Git worktree flow | Create a Git worktree from a Git Project | Action execution creates and registers the generated Project without request approval. |

E2E plan:

- Prefer existing workspace/chat E2E coverage if available for the Project panel and registration flow.
- If no product E2E coverage exists, use backend OpenAPI/client generation checks plus frontend typecheck/lint as coverage for this removal, and record the coverage gap in the PR.

Fixture/prerequisite support:

- No new testenv fixture is required. Existing runtime-backed session fixtures are sufficient for manual or future automated Project registration verification.

Evidence format:

- Include command output for backend ruff/pyright and frontend format/lint/typecheck/build checks in the PR summary.
- Include OpenAPI/client generation diffs.

CI execution policy:

- Run relevant local checks before PR creation where practical.
- After PR creation, monitor CI and fix failures without bypassing hooks.

Skip/fail criteria:

- Do not skip required checks because this removes public API and generated client surface.
- If live runtime E2E is unavailable locally, document that limitation and rely on CI plus targeted static/type checks.

## Alternatives Considered

1. Keep the table/API but hide the frontend UI.
   - Rejected because it preserves an unimplemented product contract and generated client surface.
2. Keep the table for future implementation.
   - Rejected because there is no creation path today, and future agent-initiated Project registration should be designed from current product needs rather than carrying stale state.
3. Convert requests into direct registration.
   - Rejected because existing rows cannot be trusted as user-approved, and the current implemented UX already uses direct user registration.

## Open Questions

None. The chosen direction is a removal of unimplemented behavior, with direct Project registration retained as the only current flow.
