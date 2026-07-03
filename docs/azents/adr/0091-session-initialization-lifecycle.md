---
title: "ADR-0091: Session Initialization Lifecycle"
created: 2026-07-03
tags: [architecture, backend, frontend, session]
---

# ADR-0091: Session Initialization Lifecycle

## Context

Some AgentSession startup work must happen after a session and its first input are accepted, but before the first agent run begins. Git worktree creation is the motivating case, but the same lifecycle can also cover runtime warmup, credential checks, workspace setup scripts, Project registration, catalog upsert, and catalog status refresh.

Current session creation writes an `AgentSession`, registers explicit `session_workspace_projects`, stores the first input as an `InputBuffer`, publishes pending input live state, and wakes the worker. The worker then promotes input buffers and creates an `agent_runs` row. There is no generic pre-run lifecycle gate.

A one-off worktree-specific gate would duplicate the same concerns for future session startup work and would make UI/live-state behavior inconsistent.

## Decision

### ADR-0091-D1 — Introduce one durable initialization lifecycle per AgentSession

Each `AgentSession` has a one-to-one `SessionInitialization` lifecycle. The lifecycle owns initialization status, failure summary, retry count, and terminal timestamps.

If no initialization steps are required, the lifecycle transitions to `ready` immediately. Existing sessions must be backfilled or lazily materialized as `ready` before enforcing the worker gate.

### ADR-0091-D2 — Model initialization as typed internal steps

Initialization work is represented as ordered typed backend-discovered steps. Steps are internal product lifecycle steps, not user-defined workflows and not agent tool calls.

Steps record blocking behavior, retryability, attempt number, dependencies, resource descriptors, failure reason, and timestamps. Step events are append-only durable records for UI detail views and reconnect recovery.

### ADR-0091-D3 — Gate run dispatch before input-buffer promotion

The worker must check initialization readiness before promoting input buffers or creating an `agent_runs` row.

When initialization is `pending`, `running`, `failed`, `cleanup_required`, `canceled`, or `cleaned`, the first run must not start. Pending input buffers remain pending. When initialization is `ready`, the existing run dispatch path proceeds.

This gate belongs before `RunExecutor.execute()` promotes inputs. In the current worker shape, that means `SessionRunner` or an equivalent pre-run orchestration layer, not the middle of `RunExecutor`.

### ADR-0091-D4 — Use existing chat live transport with a new initialization taxonomy

Initialization is exposed through the existing session live subscription model as a first-class live-state taxonomy beside partial history, input buffers, run, todo, and goal.

Initialization updates are not durable conversation transcript events. They must not be forced into `partial_history_events` or `history_event_appended`.

The compact live projection is available from `/live` and REST write snapshots. Expanded logs are restored from durable initialization events.

### ADR-0091-D5 — Backend owns orchestration; runner owns filesystem/command execution

Backend services own step discovery, lifecycle state, run dispatch gating, retry policy, cleanup coordination, API projections, and WebSocket/live notifications.

Runner-backed steps execute argv-based commands or typed filesystem/runtime operations, stream stdout/stderr or operation output, and report final success/failure. Runner operations do not mutate session lifecycle state directly.

### ADR-0091-D6 — Retry and cleanup are explicit lifecycle actions

Blocking failures leave input buffers pending and expose retry/delete/cleanup actions where allowed. Retry reruns the failed step and downstream dependent steps while keeping previous attempt events append-only.

Initialization does not perform destructive rollback automatically at failure time. Cleanup is descriptor-driven and runs through explicit user action, delete/archive lifecycle, or a future cleanup worker.

### ADR-0091-D7 — Retry requests run through the session broker ownership path

Initialization retry APIs record retry intent, reset retryable failed and downstream dependent steps, and enqueue the existing session broker wake-up. They do not execute runner-backed initialization work inside the HTTP request.

The session runner owns retry execution under the same per-session ownership model as normal run dispatch. On wake-up, the runner checks initialization before promoting input buffers. If initialization is not ready but retryable work is pending, it executes initialization steps first. After initialization becomes ready, the runner may continue into normal run dispatch or enqueue a follow-up wake-up according to implementation needs.

Concurrent retry requests while a retry is already pending/running return a conflict or the existing retry state. A separate initialization worker queue is out of scope for the MVP.

### ADR-0091-D8 — Initialization UI uses compact live state plus durable detail logs

Initialization appears in the chat timeline as a compact live card, not as conversation transcript. The compact projection includes initialization status, current step, blocking/failure state, warning count, and available recovery actions.

Expanded details are served from durable initialization steps and events. The detail view includes step attempts, command argv, stdout/stderr chunks, exit code, semantic failure code, and user-safe failure summary.

WebSocket delivery uses initialization-specific messages such as `session_initialization_updated` and `session_initialization_event_appended`. Initialization updates do not use `history_event_appended`, are not mirrored into durable conversation events, and are not injected into model input.

### ADR-0091-D9 — Title generation waits for initialization readiness

Initialization does not trigger LLM title generation. A session may keep `agent_sessions.title = null` while initialization is pending, running, failed, or cleanup-required.

Clients render contextual fallback copy for not-yet-titled sessions, such as a worktree source label or `Preparing session`. LLM title generation resumes through the existing post-ready run/title lifecycle after initialization becomes `ready` and normal run dispatch proceeds.

### ADR-0091-D10 — AgentSessions have a durable human-readable handle

`agent_sessions` stores a durable `handle` for each session. The handle is a stable human-readable slug that can be used by lifecycle features such as worktree path and branch naming.

Handles use a vendored snapshot of the BIP-39 English wordlist from `bitcoin/bips` as the fixed trusted word source. Azents does not generate or curate custom words. The implementation randomly selects three words and joins them with hyphens, for example `brisk-cedar-lantern`.

The database enforces global uniqueness. Generation retries on unique constraint conflicts. Existing sessions are backfilled during migration. Handles are never derived from session title, user prompt, Project path, or other potentially sensitive user content.

## Consequences

- Session startup work gets one reusable lifecycle model instead of feature-specific state machines.
- The first user message remains a normal durable input buffer.
- Run dispatch becomes dependent on a durable initialization row for first-run sessions.
- REST, WebSocket, frontend state, OpenAPI clients, and E2E fixtures need schema and rendering changes.
- Migration must establish ready initialization rows before the gate is enforced.
- Initialization command logs are recoverable after reconnect because they are durable initialization events, not Redis-only live state.

## Alternatives

### Worktree-only setup state

Rejected. Worktree setup is the first motivating case, but runtime warmup, credential checks, setup scripts, Project registration, and catalog upsert need the same first-run gate.

### Pending-message state

Rejected. Existing input buffers already represent accepted-but-not-yet-promoted user input. Adding a separate pending-message model would duplicate state and complicate write idempotency.

### Backend-only hidden setup

Rejected. Users need visible progress and failure logs for long-running setup. Hidden backend jobs would make first-run delays and Git failures opaque.

### Runner-owned orchestration

Rejected. Runner has filesystem authority, but backend owns session lifecycle, retry policy, access control, audit state, and run dispatch.

### Store initialization as conversation history

Rejected. Initialization is session lifecycle state, not conversation transcript. It should be rendered in the timeline/live UI but not injected into model history as durable chat events.
