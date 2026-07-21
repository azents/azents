---
title: "Explicit AgentSession Write Target"
tags: [backend, chat, migration, agent-session, historical-reconstruction]
created: 2026-06-25
updated: 2026-06-25
document_role: primary
document_type: design
snapshot_id: write-260625
migration_source: "docs/azents/design/explicit-agent-session-write-target.md"
historical_reconstruction: true
---

# Explicit AgentSession Write Target

## Overview

This document defines Phase 2 of the multi-active `AgentSession` migration: user input writes must target the explicitly requested `AgentSession`. Runtime-owned active/current session lookup must not redirect a write to another session.

Phase 1 already moved execution-control state such as `run_state`, `run_heartbeat_at`, pending command, and stop request fields to `AgentSession`. Phase 2 makes the write path align with that ownership: the input buffer row, live projection, broker wake-up, and write response all use the same target session id.

## Problem

The current REST message path accepts `/chat/v1/sessions/{session_id}/messages`, but `AgentSessionInputService.create_buffered_agent_input(...)` still ensures the runtime active session and stores input into that active session. This causes silent redirection:

1. caller writes to session A
2. service resolves runtime active session B
3. input buffer is created for session B
4. broker wake-up and response use session B

That behavior is incompatible with the target model where `AgentRuntime` and `AgentSession` are sibling models under `Agent` and the session is the execution-control boundary.

## Decision

Existing-session REST writes must enqueue into the path session after access validation.

For `POST /chat/v1/sessions/{session_id}/messages`:

- `session_id` from the path is the authoritative write target.
- The service validates that the session exists.
- The service validates that the session belongs to the requested `agent_id`.
- The service ensures the agent runtime only to return runtime metadata and validate the session's current denormalized runtime reference during the transition.
- The service creates the `InputBuffer` for the requested `session_id`.
- `InputBufferService.enqueue(...)` marks that same session running.
- Live projection publish, broker `SessionWakeUp`, snapshot, and response all use that same session id.

For the default team-primary chat entry, Web resolves `GET /chat/v1/agents/{agent_id}/team-primary-session` before enqueue, then writes through `POST /chat/v1/sessions/{session_id}/messages`. Once a concrete session id is resolved, the enqueue service must not replace it.

## Clean Migration Rule

This phase must not preserve runtime active/current lookup as a compatibility behavior. If a path accepts an explicit `agent_session_id`, it either writes to that exact session or fails.

Do not use these as write-routing authority:

- `AgentRuntime.current_session_id`
- `AgentSessionRepository.ensure_active(...)`
- `AgentSessionRepository.ensure_active_with_runtime_lock(...)`
- `AgentSessionRepository.get_active_by_runtime_id(...)`

Those APIs may still exist for other intermediate paths, but the explicit input enqueue path must not call them.

## Validation Rules

`AgentSessionInputService.create_buffered_agent_input(...)` validates:

1. The requested `AgentSession` exists.
2. `AgentSession.agent_id == agent_id`.
3. `AgentSession.status == active`.
4. The requested agent runtime exists for `agent_id`.
5. During the transition, `AgentSession.agent_runtime_id == AgentRuntime.id`.

Archived sessions must not receive new user message input. Returning a conflict is preferable to silently moving the write.

## Error Semantics

The service returns `Result[BufferedAgentSessionInputResult, AgentSessionInputError]` for invalid write targets. REST callers must use the existing `Success` / `Failure` match pattern rather than catching service exceptions.

Required failures:

- missing session: `AgentSessionInputSessionNotFound`
- different agent: `AgentSessionInputWrongAgent`
- different runtime during transition: `AgentSessionInputWrongRuntime`
- archived/non-active session: `AgentSessionInputInactiveSession`

## Expected Code Changes

- `AgentSessionInputService.create_buffered_agent_input(...)` loads the requested session directly.
- It removes the `ensure_active_with_runtime_lock(...)` call from the explicit enqueue path.
- It calls `EventSessionRepository.ensure_from_legacy_session(...)` for the requested session, not a runtime active session.
- It passes the requested session id to `InputBufferEnqueue`.
- Unit/integration tests assert that stale archived session ids are rejected instead of redirected.
- Unit tests assert the active-session repository method is not part of the call sequence.

## Spec Updates

`docs/azents/spec/domain/conversation.md` should be updated to state:

- Direct session write routes target the path session.
- Runtime current/active session lookup is invalid for direct session writes.
- Input buffers are session-scoped.
- Broker wake-up and live projection use the same target session id as the created input buffer.
