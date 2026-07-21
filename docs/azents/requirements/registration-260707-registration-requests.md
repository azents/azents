---
title: "Remove Project Registration Requests Historical Requirements Reconstruction"
created: 2026-07-07
implemented: 2026-07-07
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: registration-260707
historical_reconstruction: true
migration_source: "docs/azents/design/remove-project-registration-requests.md"
---

# Remove Project Registration Requests Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `registration-260707`
- Source: `docs/azents/design/registration-260707-registration-requests.md`
- Historical source date basis: `2026-07-07`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

`session_workspace_project_registration_requests` exists as a database table, ORM model, repository/service surface, public API, generated client surface, and azents-web panel UI. The product concept behind it is not implemented end to end: there is no agent-facing tool, command, or service path that creates a registration request. The only implemented user-facing Project registration flow is direct user registration of an existing Agent Workspace directory, plus Git worktree creation through durable `create_git_worktree` actions.

This change removes the unimplemented Project registration request concept so the current Project model contains only implemented behavior.

Goals:

- Remove the dead `session_workspace_project_registration_requests` storage contract with a forward Alembic migration.
- Remove backend repository, service, enum, and public API code that only serves registration requests.
- Regenerate public API clients after the public API contract changes.
- Remove azents-web registration request UI and tRPC methods.
- Update living specs so they describe current behavior without the request/approval flow.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

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

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
