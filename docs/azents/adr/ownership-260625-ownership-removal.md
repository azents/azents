---
title: "Remove AgentSession Runtime Ownership"
created: 2026-06-25
tags: [architecture, backend, engine, migration, historical-reconstruction]
document_role: primary
document_type: adr
snapshot_id: ownership-260625
historical_reconstruction: true
migration_source: "docs/azents/adr/0075-agent-session-runtime-ownership-removal.md"
---

# ownership-260625/ADR: Remove AgentSession Runtime Ownership

## Context

[primary-260625/ADR](./primary-260625-primary-sessions.md) defines `AgentSession` and `AgentRuntime` as sibling models owned by `Agent`.
Phase 3 introduced team primary session semantics, but the implementation still retained an
`agent_sessions.agent_runtime_id` ownership edge and repository methods centered on runtime-owned
active sessions. That kept a hidden global session selector in the runtime model and made future
multi-session support unsafe.

## Decision

Remove `agent_sessions.agent_runtime_id` and make `AgentSession` ownership agent/session based.

Implementation decisions:

- `AgentSession` rows are identified by `workspace_id` and `agent_id`; runtime identity is not part of
  session construction or ownership.
- The team primary invariant is represented by `agent_sessions.primary_kind = 'team_primary'` with a
  partial unique constraint on `agent_id` for active team primary sessions.
- Runtime-keyed repository APIs such as active-session ensure/rotate methods are removed.
- The event-session repository facade is folded into `AgentSessionRepository`; transcript head state
  lives on `AgentSession.model_input_head_event_id`.
- Direct writes validate the requested session first, then look up or ensure runtime only to wake the
  worker for already-selected session work.
- Rotate/reset session semantics are removed. Compaction is head-based and must update
  `model_input_head_event_id` rather than creating a new session.

## Consequences

- Session ownership and selection no longer depend on runtime current/active session state.
- Existing runtime-scoped project registration and runtime-scoped idempotency are intentionally left
  for later phases; they are not session ownership edges.
- Downgrading to an older version requires best-effort reconstruction of `agent_runtime_id` from
  `agent_runtimes.agent_id`; sessions that cannot be mapped are deleted before restoring the legacy
  non-null foreign key.
- Future multiple team sessions can be added without reintroducing a runtime current-session pointer.

## Migration provenance

- Historical source filename: `0075-agent-session-runtime-ownership-removal.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
