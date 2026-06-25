---
title: "ADR-0077: Session-Owned REST Write Idempotency"
created: 2026-06-25
tags: [architecture, backend, migration]
---

# ADR-0077: Session-Owned REST Write Idempotency

## Context

ADR-0074 makes `AgentSession` the conversation boundary. ADR-0075 removes runtime ownership from
`AgentSession`, and ADR-0076 moves the project registry to session ownership. The remaining REST chat
write idempotency table still uses `agent_runtime_id` as part of its durable uniqueness scope.

Runtime-scoped REST write idempotency conflicts with URL-selected sessions because an idempotency key
is a property of a session write boundary, not a physical runtime workspace. Keeping runtime in the
idempotency key would preserve hidden runtime-global write state after session ownership has moved to
`AgentSession`.

## Decision

Move REST chat write idempotency ownership from `AgentRuntime` to `AgentSession`.

Implementation decisions:

- `chat_write_requests` belongs to `AgentSession` through `session_id`.
- The idempotency uniqueness scope is `(session_id, user_id, client_request_id)`.
- `agent_runtime_id` is removed from `chat_write_requests`.
- Edit and command REST write paths lock the target `AgentSession`; they do not ensure or use
  `AgentRuntime` as part of idempotency acceptance.
- Reusing a `client_request_id` with a different session creates an independent idempotency scope.
  URL/session mismatch is handled by session access and agent/session validation, not by runtime
  idempotency lookup.
- Runtime lookup remains valid only for runtime lifecycle and physical workspace operations, not for
  REST write idempotency ownership.

## Consequences

- REST write retries are scoped to the explicit session route that accepted the write.
- A stale retry cannot accidentally resolve through a runtime-global record from another session.
- Phase 6 can remove session-less write routes and make URL `session_id` the Web source of truth.
- Downgrading requires best-effort reconstruction of `agent_runtime_id` through
  `agent_sessions.agent_id`. Rows that cannot be mapped back to a runtime are deleted before
  restoring the legacy non-null runtime foreign key.
