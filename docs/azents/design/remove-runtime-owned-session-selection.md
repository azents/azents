---
title: "Remove Runtime-Owned Session Selection"
tags: [backend, frontend, database, migration, agent-session]
created: 2026-06-25
updated: 2026-06-25
---

# Remove Runtime-Owned Session Selection

## Overview

This document defines Phase 3 of the multi-active `AgentSession` migration: remove runtime-owned session selection from schema, repositories, services, API, and frontend entry flow.

After Phase 2, direct message writes already target the explicit `AgentSession`. Phase 3 removes the remaining runtime-owned active/current pointer so `AgentRuntime` no longer decides or stores which session is selected.

## Problem

`AgentRuntime.current_session_id` encodes a parent/child relationship that is not part of the target model. It causes these problems:

- It makes `AgentRuntime` appear to own session selection.
- Repository methods can still look up runtime by current session.
- Session ensure/rotation still mutates runtime state.
- Public API still exposes `/agents/{agent_id}/active-session` terminology.
- The web Chat tab fetches an active session before mounting chat, forcing a selected-session concept even when no message has been sent.

This conflicts with the target model where an `Agent` has one `AgentRuntime` and many independent `AgentSession` rows.

## Decision

Remove runtime-owned session selection completely.

The target after this phase:

- `agent_runtimes.current_session_id` does not exist.
- `AgentRuntime` domain models do not expose `current_session_id`.
- `AgentRuntimeRepository` has no current-session lookup or setter methods.
- `AgentSessionRepository.ensure_active(...)` does not use `AgentRuntime.current_session_id`.
- session rotation creates/archives sessions without updating runtime state.
- `/chat/v1/agents/{agent_id}/active-session` is removed.
- the web Chat tab starts without a session id and lets `/sessions/new/messages` create the first session.

## Non-Goals

This phase does not remove the single-active-session uniqueness constraint. Only one active session may still exist per runtime/agent in the current product state. Phase 4 will redefine open/active session semantics and remove that uniqueness constraint.

This phase also does not introduce a selected-session product state. If selection is needed later, it must be modeled outside `AgentRuntime` with new names.

## Database Migration

Generate an Alembic revision and remove:

- foreign key `fk_agent_runtimes_current_session_id_agent_sessions`
- index `ix_agent_runtimes_current_session_id`
- column `agent_runtimes.current_session_id`

Downgrade may recreate the nullable column, index, and foreign key, but it does not need to recover the historical selected session because the target migration is clean and selected-session state is intentionally removed.

## Repository Changes

Remove from `AgentRuntimeRepository`:

- `get_by_current_session_id(...)`
- `lock_by_current_session_id(...)`
- `set_current_session(...)`

Remove `current_session_id` from:

- `RDBAgentRuntime`
- `AgentRuntime` domain model
- `_build(...)`
- repository tests and service test fixtures

Update `AgentSessionRepository` so active session creation is based on the active session row only:

- `ensure_active(...)` fetches runtime by id only for workspace/agent/runtime metadata.
- `_ensure_active_for_runtime(...)` checks `get_active_by_runtime_id(...)`.
- if absent, it creates an active session with the existing partial unique index conflict guard.
- it never reads or writes `runtime.current_session_id`.
- rotation never writes runtime state.

This is still an intermediate implementation because the repository API remains runtime-id-centered until Phase 4. The important Phase 3 invariant is that runtime no longer stores or owns session selection.

## API Changes

Remove:

```http
GET /chat/v1/agents/{agent_id}/active-session
```

Do not replace it with an alias. Clean migration means old active/current vocabulary is deleted.

Existing clients should either:

- start Chat with no session id and use `POST /chat/v1/sessions/new/messages` for the first message, or
- use direct session routes after a concrete session id is known.

## Frontend Changes

The Agent Chat tab should not fetch an active session on mount.

Expected behavior:

- Chat tab mounts `ChatSessionView` with `initialSessionId = null`.
- First message sends through `sendMessage` with `sessionId = null`.
- The REST response returns the created session id.
- The existing `onInnerSessionCreated(...)` callback stores that concrete session id in local component state.
- Refreshing the Agent Chat tab no longer auto-selects a historical active session through backend runtime state.

This is acceptable for Phase 3 because selected-session persistence is explicitly not part of runtime state. A later product phase can add selected-session UI state with new terminology if needed.

## Context Inspector

Context inspector must not use runtime current-session lookup. Until multi-session selection exists, it may read the currently active/non-archived session row for the agent as an intermediate query, but that lookup belongs to `AgentSessionRepository`, not `AgentRuntime`.

## Validation

- `current_session_id` no longer appears in runtime model or runtime repository code.
- `/active-session` route no longer appears in public API implementation or generated OpenAPI.
- frontend no longer imports or calls `chatV1GetActiveAgentSession`.
- tests cover session ensure/rotation without runtime pointer updates.
- pre-commit regenerates OpenAPI and client output.
