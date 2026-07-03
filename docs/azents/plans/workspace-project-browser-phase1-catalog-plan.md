---
title: "Workspace Project Browser Phase 1 Catalog Plan"
created: 2026-07-03
tags: [workspace, project, backend, runtime, plan]
---

# Workspace Project Browser Phase 1 Catalog Plan

## Covered Requirements

- REQ-WPB-6 — Agent Project catalog stores reusable status projection
- REQ-WPB-7 — Manifest reads are non-blocking, foundation only
- REQ-WPB-8 — Boundary-triggered Project status sync, foundation only

Source documents:

- [Workspace Project Browser Design](../design/workspace-project-browser.md)
- [Workspace Project Browser Implementation Plan](workspace-project-browser-implementation-plan.md)
- [ADR-0090: Backend Project Browser Manifest](../adr/0090-backend-project-browser-manifest.md)

## Phase Goal

Introduce the backend data model and service foundation for an Agent-scoped Project catalog with filesystem status projection. This phase does not add the final manifest API and does not change frontend behavior.

The implementation must preserve the current session-owned Project registry. The catalog is a reusable read model and status projection, not the canonical Project identity for a session binding.

## Previous Phase Output Consumed

The multi-phase plan defines Phase 1 as the catalog/status projection foundation. Existing code already contains:

- `agent_project_presets` for recent Project path presets;
- `agent_project_defaults` for new-session default selected paths;
- `session_workspace_projects` for session-owned Project bindings;
- `AgentWorkspaceFileService` and runner operation clients for runtime file inspection.

## Output Provided to Next Phase

Phase 2 needs:

- a durable Agent-scoped catalog table/model/repository;
- a status enum or equivalent typed state for Project filesystem projection;
- idempotent catalog upsert/list methods;
- a service method that can request status sync without requiring manifest reads to block;
- tests proving catalog state can be read by Agent/path before a session exists.

## Data Model Plan

Add a new RDB model rather than overloading `agent_project_presets`.

Likely file additions/changes:

- `python/apps/azents/src/azents/core/enums.py`
  - Add `AgentProjectCatalogStatus` or similarly named `StrEnum`.
  - Initial values should cover `UNCHECKED`, `AVAILABLE`, `MISSING`, `UNAVAILABLE`, and `ERROR`.
- `python/apps/azents/src/azents/rdb/models/agent_project_catalog.py`
  - New table, for example `agent_project_catalog_entries`.
  - Columns:
    - `id` string primary key;
    - `agent_id` foreign key to `agents.id` with cascade delete;
    - `path` text, absolute Agent Workspace path;
    - `status` PostgreSQL enum;
    - `status_detail` nullable text;
    - `checked_at` nullable timezone-aware timestamp;
    - `created_at`, `updated_at`.
  - Constraints/indexes:
    - unique `(agent_id, path)`;
    - index `(agent_id, updated_at)` or `(agent_id, path)` for manifest lookup.
  - Follow azents RDB conventions: named constants for constraints/indexes and PostgreSQL ENUM columns.
- `python/apps/azents/src/azents/rdb/models/__init__.py` if models are explicitly imported there.
- Alembic migration under `python/apps/azents/db-schemas/rdb/migrations/versions/` generated with `alembic revision`.
- `python/apps/azents/db-schemas/rdb/revision` updated to the new revision id.

Migration behavior:

- Create the enum type.
- Create the catalog table.
- Backfill catalog rows from existing `agent_project_presets` as `UNCHECKED` with `checked_at = NULL`.
- Do not alter `session_workspace_projects` in this phase.
- Downgrade drops the table and enum. No attempt is needed to reconstruct catalog rows because presets remain separate.

## Repository and Domain Model Plan

Add a repository package:

- `python/apps/azents/src/azents/repos/agent_project_catalog/data.py`
- `python/apps/azents/src/azents/repos/agent_project_catalog/__init__.py`

Domain models should include:

- `AgentProjectCatalogEntry`
- `AgentProjectCatalogEntryCreate` or direct repository arguments for upsert
- status patch/update input, preferably a frozen dataclass or Pydantic model when more than one field is updated

Repository methods needed by Phase 2:

- `upsert_entry(session, *, agent_id, path, status=None)`
  - inserts new path as `UNCHECKED` by default;
  - on conflict updates `updated_at` and preserves existing status unless explicitly patched.
- `list_entries(session, *, agent_id)`
  - order by recent update then path, or path depending on manifest needs.
- `get_entry_by_path(session, *, agent_id, path)`
- `list_entries_by_paths(session, *, agent_id, paths)`
  - needed for manifest construction.
- `update_status(session, *, agent_id, path, status, status_detail, checked_at)`
  - upsert-safe, so sync can update a path even if only a path candidate was known.

Repository tests:

- create/upsert idempotency;
- conflict refresh does not duplicate rows;
- list by paths preserves lookup correctness;
- status update records checked timestamp and detail;
- backfilled unchecked semantics can be represented.

## Service Plan

Add a service package or module for catalog/status sync, likely:

- `python/apps/azents/src/azents/services/agent_project_catalog/__init__.py`

Service responsibilities:

- Normalize/validate Project paths by reusing `normalize_session_workspace_path` from `services/session_workspace_project`.
- Upsert Project candidates for an Agent without requiring a session.
- Upsert many Project candidates for session bootstrap.
- Refresh status for one or more paths when runtime access is available.
- Return `UNAVAILABLE` status when runtime/runner is absent or not ready.
- Convert runner stat/list failures into `MISSING` or `ERROR` projection without raising as manifest-read failure.

Suggested service methods:

- `upsert_project_candidate(agent_id, path)`
- `upsert_project_candidates(agent_id, paths)`
- `refresh_project_status(agent_id, path)`
- `refresh_project_statuses(agent_id, paths)`
- `list_catalog_entries(agent_id)`
- `list_catalog_entries_by_paths(agent_id, paths)`

Runtime inspection details:

- Use `AgentRuntimeRepository.get_by_agent_id` to find runtime.
- If runtime is missing or runner is not READY, update status to `UNAVAILABLE` with a short detail.
- If runtime is ready, use `RuntimeRunnerOperationClient.stat_file` for the path.
- A directory result maps to `AVAILABLE`.
- A missing result or runner failure indicating not found maps to `MISSING` when distinguishable.
- Other known runner failures map to `ERROR` with detail.
- `asyncio.CancelledError` must be re-raised.

This phase may implement synchronous service methods that perform status refresh when explicitly called. Phase 2 will decide which call sites enqueue them non-blockingly.

## Integration Plan for Existing Call Sites

This phase should add low-risk catalog upsert integration where it does not change user-visible behavior:

- `ChatSessionService._create_session_projects()`
  - after current preset/default behavior, upsert catalog candidates for selected paths.
- `AgentSessionInputService._create_session_projects()`
  - mirror the same catalog candidate upsert for first-message session creation.
- `SessionWorkspaceProjectService.register_existing_folder_for_session()`
  - after successful Project registration, upsert the catalog candidate.
- `SessionWorkspaceProjectService.approve_registration_request_for_session()`
  - after successful approval, upsert the catalog candidate.

Status refresh may be added in this phase only if it is explicit and does not block an existing read path. Do not change existing API response behavior.

## Test Plan

Backend unit tests should be added/updated for:

- `AgentProjectCatalogRepository` CRUD/upsert/status behavior;
- `AgentProjectCatalogService` path validation and candidate upsert behavior;
- session creation path upserts catalog rows without changing session Project rows;
- direct Project registration and approval upsert catalog rows;
- refresh behavior maps runtime missing/not ready to `UNAVAILABLE`;
- refresh behavior maps available directory to `AVAILABLE` using a runner operation fake.

Likely test files:

- `python/apps/azents/src/azents/repos/agent_project_catalog/repository_test.py`
- `python/apps/azents/src/azents/services/agent_project_catalog/service_test.py`
- existing tests in:
  - `python/apps/azents/src/azents/services/chat/team_session_test.py`
  - `python/apps/azents/src/azents/services/agent_session_input_test.py`
  - `python/apps/azents/src/azents/services/session_workspace_project/service_test.py`

Quality checks for this phase:

```console
cd python/apps/azents
uv run ruff check --fix .
uv run ruff format .
uv run pyright
uv run pytest src/azents/repos/agent_project_catalog src/azents/services/agent_project_catalog src/azents/services/session_workspace_project src/azents/services/chat src/azents/services/agent_session_input
```

If the full listed pytest scope is too slow, run the newly added tests and directly affected existing test files, then document the subset in the PR body.

## Completion Criteria

- New catalog table/model/repository/service exists.
- Migration is generated through Alembic and `revision` is updated.
- Existing session Project and preset/default behavior continues to pass tests.
- Catalog rows are upserted at session creation, existing Project registration, and approval success boundaries.
- Status projection refresh can be invoked by Phase 2 without introducing runner calls into manifest read paths.
- No frontend behavior changes are included in this phase.

## Open Questions

No blocker is known. If the migration tooling or current schema state prevents a clean new table migration, stop and report the migration conflict rather than hand-writing a migration outside the approved Alembic workflow.
