---
title: "Primary Agent Sessions Migration Phases"
created: 2026-06-25
updated: 2026-06-25
tags: [architecture, backend, frontend, engine, migration]
---

# Primary Agent Sessions Migration Phases

## Overview

This document defines the incremental migration plan toward the target state in [Primary Agent Sessions Target Design](./primary-agent-sessions.md), based on [ADR-0074](../adr/0074-primary-agent-sessions.md).

The target design is the source of truth for final behavior. This document is only the implementation sequencing guide.

## Migration Principles

1. Preserve default team conversation behavior while removing runtime-owned session selection.
2. Do not expose multiple sessions before explicit session writes and session-owned execution state are stable.
3. Do not implement private sessions in the first delivery.
4. Do not implement git worktree automation in the first delivery.
5. Do not implement primary clear semantics in the first delivery.
6. Keep runtime/session ownership separation visible in every phase.
7. Keep project ownership session-scoped once project migration begins.

## Phase 0: Restore safe baseline and close incorrect migration branch

### Goal

Undo the incorrect path that removed active/default session behavior before primary session semantics were defined.

### Scope

- Close the obsolete implementation PR that removed the active-session endpoint and forced Web chat to start without resolving a default session.
- Keep the accepted design documents as separate documentation work.
- Treat old active-session behavior as a compatibility entrypoint until replaced by team primary terminology.

### Exit Criteria

- No implementation branch removes default session behavior without primary-session replacement.
- Target design and ADR are merged independently.

## Phase 1: Session-owned execution state foundation

### Goal

Make `AgentSession` the durable owner of execution-control state.

### Scope

Move or keep these state fields on `AgentSession`:

- `run_state`
- `run_heartbeat_at`
- pending command fields
- stop request fields
- stuck-running recovery target

Runtime remains responsible for provider lifecycle, runner connectivity, and physical workspace identity.

### Exit Criteria

- Worker recovery scans session run state, not runtime run state.
- Stop requests and pending commands target one session.
- Runtime no longer acts as the run-state source of truth.

## Phase 2: Explicit session write target

### Goal

Ensure writes to an explicit session ID cannot silently redirect to another session.

### Scope

- REST session message writes use the path/request session as the target.
- `AgentSessionInputService` validates agent/session membership but does not replace the requested session with runtime current session.
- Broker wake-up uses the same session ID that received the input buffer.
- Error handling returns REST boundary errors for missing/wrong/inactive sessions.

### Exit Criteria

- Writing to session A enqueues input for session A.
- Existing default/new-message routes may still resolve the default session, but explicit session routes remain authoritative.

## Phase 3: Introduce team primary session semantics

### Goal

Reinterpret the old active/default session as the agent's team primary session without exposing multi-session yet.

### Scope

- Add agent-owned primary session lookup/ensure semantics.
- Keep compatibility route(s) if needed, but make them resolve the team primary session without runtime current-session state.
- Add or prepare schema invariants for one team primary session per agent.
- Do not implement private sessions.
- Do not implement clear semantics.

### Exit Criteria

- Agent chat default entry resolves a team primary session.
- Runtime current-session fields and repository APIs are no longer used for default session selection.
- Compatibility active-session API, if still present, is only a wrapper over team primary lookup.

## Phase 4: Remove runtime/session ownership dependency

### Goal

Make `AgentSession` an agent-owned model, not a runtime child.

### Scope

- Remove `AgentSession` construction requirements that depend on `agent_runtime_id`.
- Remove runtime-keyed active-session uniqueness.
- Replace runtime-keyed session repository methods with agent/session methods.
- Merge the old event-session facade into `AgentSessionRepository`.
- Remove rotate/reset session semantics; compaction advances `model_input_head_event_id` instead.
- Keep runtime lookup only for runtime services needed after a session has already been selected.

### Exit Criteria

- Session ownership is represented through `agent_id`.
- Runtime is not the ownership edge or selection authority for sessions.
- Tests can create/fetch sessions through agent/session ownership paths.
- No runtime-keyed active/rotate repository API remains.

### Implementation Status

Phase 4-A removes `agent_sessions.agent_runtime_id`, deletes runtime-owned active/rotate session
repository APIs, and treats `AgentSession.model_input_head_event_id` as the event transcript head.
Runtime-scoped project registration and REST write idempotency remain as follow-up ownership cleanup.

## Phase 5: Session-owned projects

### Goal

Move project registrations into session working context.

### Scope

- Introduce session project registration storage.
- Move or migrate existing project associations into the team primary session.
- New sessions later copy projects from the team primary session.
- Do not add selected/current/active project state.
- Do not add git worktree automation.

### Exit Criteria

- Project rows belong to sessions.
- Runtime has no current project or project catalog ownership role.
- The team primary session contains the agent's initial project working context.

## Phase 6: URL-selected Web session

### Goal

Make Web selected session route state.

### Scope

- Add canonical session route:

```text
/w/{handle}/agents/{agent_id}/sessions/{session_id}
```

- Make the agent chat entry route resolve the team primary session and navigate to the canonical route.
- Load chat history/live state from the session ID in the route.
- Preserve selected session across refresh/share/back-forward navigation.

### Exit Criteria

- Reloading the canonical route loads the same session.
- Agent chat no longer depends on local-only selected session state.
- Runtime state is not involved in Web session selection.

## Phase 7: Multiple team sessions

### Goal

Expose explicit additional team sessions under one agent.

### Scope

- Add agent-scoped team session list API with primary first.
- Add create team session API.
- On create, snapshot-copy the team primary session's projects into the new session.
- Add Team sessions list UI.
- Add New team session UI.
- Explicit session write/history/live APIs continue to target the selected session.

### Exit Criteria

- An agent can have team primary plus additional team sessions.
- Users can switch sessions through URL-backed navigation.
- Creating a new team session copies primary projects once.
- Writing to a non-primary session does not affect team primary.

## Phase 8: External shared routing to team primary

### Goal

Make shared external inputs target the team primary session by default.

### Scope

- Shared external events resolve the target session through team primary lookup.
- Do not expose arbitrary channel/session mapping UI.
- Do not route private inputs yet.

### Exit Criteria

- Shared external channel inputs do not create hidden per-channel sessions by default.
- Shared external inputs do not depend on runtime current-session state.
- Team primary remains the continuity-preserving external workflow target.

## Deferred Future Phases

### Private sessions

Future work:

- Add Private sessions section.
- Add user private primary session per `(agent_id, user_id)`.
- Add private authorization and visibility enforcement.
- Route private external inputs such as Slack DMs to user private primary.
- Define private memory promotion policy.

### Primary clear/reset

Future work:

- Define clear semantics for transcript, context, input buffers, goal/todo state, and artifacts.
- Preserve primary non-deletability.
- Decide whether clear is generation-based, archive-based, or marker-based.

### Git worktree automation

Future work:

- Provide optional worktree creation as a session project bootstrap action.
- Keep Git as an optional integration/tooling convenience unless a later ADR makes it first-class.

### User-facing scheduled agent work

Future work:

- Revisit agent-created scheduled work after team sessions and private sessions are stable.
- Decide whether schedule runs use team primary, private primary, dedicated sessions, or another model.

## Verification Strategy By Phase

Each implementation phase should include product-path verification when behavior changes.

| Phase | Primary verification |
|---|---|
| Phase 1 | Worker/session recovery tests and E2E where available. |
| Phase 2 | API/WebSocket E2E for explicit session writes. |
| Phase 3 | API/Web E2E for default team primary resolution. |
| Phase 4 | Repository/service tests plus API E2E to confirm no runtime-current redirect. |
| Phase 5 | API/repository tests for session project ownership and migration. |
| Phase 6 | Web E2E for canonical session URL reload/share behavior. |
| Phase 7 | Web/API E2E for session list, create, switch, and write isolation. |
| Phase 8 | Integration or testenv path for shared external routing when available. |

## Relationship to Abandoned Design

This phased plan supersedes [Abandoned Multi-Active AgentSession Migration Overview](./multi-active-agent-sessions-overview.md).

The main differences are:

- It preserves default behavior as team primary rather than removing active/default behavior immediately.
- It keeps private sessions deferred.
- It makes projects session-owned.
- It defers git worktree automation and primary clear semantics.
- It separates target-state design from implementation phase sequencing.
