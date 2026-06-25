---
title: "ADR-0076: Session-Owned Project Registry"
created: 2026-06-25
tags: [architecture, backend, engine, migration]
---

# ADR-0076: Session-Owned Project Registry

## Context

ADR-0074 defines project registrations as `AgentSession` working context, while
`AgentRuntime` owns only the physical workspace and runtime lifecycle. Phase 4-A removed
`AgentSession` runtime ownership, but the existing `session_workspace_projects` and project
registration request tables still use `agent_runtime_id` as their durable ownership key.

Keeping project rows runtime-owned would recreate hidden runtime-global context. It would also make
future URL-selected sessions and multiple team sessions ambiguous because different sessions under the
same agent would see the same project catalog by default.

## Decision

Move the project registry and project registration request registry from runtime-owned to
session-owned.

Implementation decisions:

- `session_workspace_projects` belongs to `AgentSession` through `session_id`.
- `session_workspace_project_registration_requests` belongs to `AgentSession` through `session_id`.
- Existing runtime-owned rows are backfilled to the agent's active team primary session.
- Rows that cannot be mapped to an active team primary session are invalid legacy rows and are
  deleted during migration.
- Agent-scoped public project routes may remain compatibility entrypoints during Phase 5-A, but they
  resolve the agent's team primary session before reading or writing project rows.
- Runtime lookup remains allowed only for physical workspace validation and runner filesystem
  operations after the session project context has been selected.
- RuntimeToolkit loads registered project prompt content from the current logical `AgentSession` ID.
  Runtime context sharing affects filesystem operations only; it must not make project registry
  ownership fall back to a parent or runtime session.
- Do not add runtime current project, selected project, active project, or project catalog state.

## Consequences

- Project context follows the selected session instead of the runtime.
- Future team sessions can snapshot-copy team primary projects into independent session-owned rows.
- The same physical path may be registered by multiple sessions because runtime workspace paths are
  physical resources, not project ownership keys.
- Existing project rows that cannot be assigned to a team primary session are discarded rather than
  creating sessions implicitly in the migration.
- Subagents or other runtime-sharing flows may use the same physical runtime workspace while still
  receiving project prompt context from their logical session.
- Downgrading requires best-effort reconstruction of `agent_runtime_id` from
  `agent_sessions.agent_id`; rows that cannot be mapped back to a runtime are deleted before
  restoring legacy non-null runtime foreign keys.
