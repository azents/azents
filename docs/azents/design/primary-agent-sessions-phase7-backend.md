---
title: "Primary Agent Sessions Phase 7-A Backend Plan"
created: 2026-06-26
updated: 2026-06-26
tags: [architecture, backend, api, testing]
---

# Primary Agent Sessions Phase 7-A Backend Plan

## Context

Phase 6 made the Web-selected session URL-backed through
`/w/{handle}/agents/{agent_id}/sessions/{session_id}`. The remaining Phase 7 work is to expose
multiple team sessions under one agent.

This plan intentionally stops before the session-list/switch/create Web UI. It prepares the backend,
public API, generated clients, and deterministic E2E coverage so a follow-up UI PR can consume a stable
contract.

## Goals

- List active team sessions for one agent with the team primary session first.
- Create a non-primary team session for an agent.
- Snapshot-copy the team primary session's registered projects into the new session at creation time.
- Preserve explicit session write/history/live isolation.
- Keep private sessions, session naming/renaming, session deletion, and session-scoped project editing out of scope.

## Non-goals

- Do not add the Web session list, session switcher, or new-session button in this phase.
- Do not add private session visibility or authorization semantics.
- Do not add a session title/name column.
- Do not change agent-scoped project routes; they remain team-primary compatibility entrypoints.
- Do not copy pending project registration requests.

## API contract

Add agent-scoped session APIs:

```text
GET /chat/v1/agents/{agent_id}/sessions
POST /chat/v1/agents/{agent_id}/sessions
```

`GET` returns active team sessions visible to the requester. The team primary session appears first.
Remaining sessions are ordered by most recently updated first.

`POST` creates one active non-primary team session and returns it. The request body is empty for the
Phase 7-A contract because sessions are unnamed.

`AgentSessionResponse` should expose enough metadata for a future UI to distinguish the primary
session without guessing:

- `id`
- `agent_id`
- `status`
- `primary_kind`
- `created_at`
- `updated_at`

The UI can treat `primary_kind == "team_primary"` as the primary badge. No `is_primary` boolean is
added because azents field naming conventions avoid `is_` prefixes and the enum already carries the
source of truth.

## Session creation semantics

Creating a team session performs one database transaction:

1. Load the agent.
2. Verify the requester is a member of the agent workspace.
3. Ensure the agent's team primary session exists.
4. Create a new active `AgentSession` with `primary_kind = null`.
5. Copy all registered `session_workspace_projects` from the team primary session to the new session.
6. Commit and return the created session.

Project copy uses the already-registered primary project rows as the source of truth. It must not
re-run runner filesystem validation, because a new logical session should not fail merely because the
runtime is currently disconnected.

Pending project registration requests are not copied. They represent unresolved approval workflow
state for the source session, not durable working context.

## Isolation requirements

- Writing to the new session must append input/history only to that session.
- Writing to the new session must not change the team primary transcript.
- Registering a project on the team primary after a non-primary session is created must not
  retroactively modify the non-primary session.
- A non-member must receive the same not-found semantics already used for agent/session access checks.

## Follow-up UI phase

The UI phase should consume these APIs through generated clients and tRPC wrappers. It should add a
Team sessions selector/rail and a New team session action that navigates to the canonical URL returned
by the create API.
