---
title: "ADR-0040: Manage Toolkit Lifecycle by AgentSession Lifecycle"
created: 2026-05-29
tags: [architecture, backend, engine, toolkit]
---

# ADR-0040: Manage Toolkit Lifecycle by AgentSession Lifecycle

## Context

ADR-0013 introduced the Toolkit State Machine and decided that toolkit background work lifecycle should be scoped to `_SessionRunner`. The engine reads only current state through `update_context()` on each turn, while heavy work such as MCP connection and tool listing should be managed by the toolkit in the background.

Current implementation does not fully satisfy this decision. The worker calls `resolve_agent_tools()` on every message to create new toolkit instances, and `_SessionRunner` calls `__aenter__()` on the toolkit list returned from the first run only after the canonical engine calls `update_context()`. Therefore, the first run executes `update_context()` without `__aenter__()`, causing MCP-based toolkits to take sync fallback. In later runs, newly resolved toolkit instances are not under `__aenter__()`/`__aexit__()` management.

This cannot be fixed merely by moving `__aenter__()` earlier. Some toolkits capture a mix of state that is safe to reuse for a session and state that changes per run.

- MCP/AWS/GCP toolkits are well-suited for session-scoped background connection state.
- `ScheduleToolkit` captures the full `ToolkitContext` in the constructor, so `run_id`, `publish_event`, and `user_id` can become stale.
- Subagent tool wrapper captures `parent_run_id`, `parent_check_stop`, `publish_event`, and `user_id` at run time.
- MCP per-user OAuth and GitHub per-user PAT select tokens by `user_id` at resolve time, so if actor changes inside a session, stale credential risk appears.

ADR-0033 runtime hook system also uses Toolkit as the runtime capability provider boundary. Provider list and hook ordering depend on resolved toolkit snapshot, so session-scoped toolkit reuse must clearly separate hook provider snapshot from per-run hook context.

## Decision

Toolkit instances and `__aenter__()`/`__aexit__()` lifecycle are bound to the `_SessionRunner` active lifetime keyed by `agent_sessions.id`. Runs or messages do not own toolkit instances.

While a session runner is active, the worker keeps the toolkit registry for that same session. Before a new run starts, it resolves or reconciles that session's toolkit set, and session-managed toolkits must be entered before engine `update_context()` runs. When the session runner terminates due to idle timeout, shutdown, or explicit termination, it cleans up entered toolkits in reverse order. This cleanup is guaranteed by a structured cleanup primitive such as `AsyncExitStack`.

Toolkit context is split by these boundaries:

- Session-stable context: `session_id`, `workspace_id`, `agent_id`, `session_type`, interface identity, static configuration, long-lived service clients, background state.
- Turn/run context: `run_id`, `publish_event`, current actor `user_id`, model, stop checker, per-run hook context.

Session-managed toolkits do not capture run-scoped values in constructor or provider `resolve()` results. If a tool handler needs run-scoped values, it returns a handler that captures current turn values inside `update_context(TurnContext)`. If `TurnContext` does not provide required fields, add fields or introduce a separate per-turn handler context. Do not bypass this with ad-hoc narrowing based on `hasattr`/`getattr` or `typing.cast()`.

Toolkits using per-user credentials keep session-scoped instances, but credential selection and refresh happen by current `TurnContext.user_id`. Entry points where actor can change inside one session must not reuse stale user token. System sessions keep the existing policy disabling per-user OAuth.

Runtime hooks are registered from session-scoped provider instances, but hook context is created from current context at every run/turn/tool dispatch. `on_session_start` dispatches once through existing `agent_sessions.lifecycle_started_at` claim, while `on_run_start`/`on_run_end` dispatch on every run with latest `run_id`.

Session lifecycle migration does not require destructive schema migration or transcript migration. This ADR only covers toolkit object lifecycle and runtime execution semantics.

## Considered Options

### Option A — Create toolkit per run and enter before run start

This can remove the sync fallback bottleneck on first run. However, it does not satisfy ADR-0013's session-scoped background state decision, and toolkits such as MCP/GCP/AWS repeat connection/listing on every message. Run-scoped capture issues also remain. Not adopted.

### Option B — Reuse only DB-registered toolkits as session-scoped

This can quickly reduce major bottlenecks for MCP/GitHub/EnvVar. But builtin, schedule, subagent, background task, and hook provider snapshot would keep different lifecycle models, splitting the worker mental model in two. It may be possible as a temporary hotfix, but is not adopted as target state.

### Option C — Make all toolkits session-scoped and separate run-scoped values

This matches ADR-0013's passive loading decision and lets worker simply treat session runner as toolkit lifecycle owner. It requires context split for `ScheduleToolkit`, subagent, and per-user credential toolkits. This option is adopted.

### Option D — Separate Toolkit and RuntimeCapabilityProvider

This could make names and responsibilities more accurate. But ADR-0033 decided to keep current Toolkit boundary as runtime capability provider boundary, and this problem is about lifecycle ownership and context boundary rather than a new abstraction. Not adopted.

## Consequences

- `_SessionRunner` owns toolkit registry and structured cleanup.
- `EngineWorker.process_message()` must use session-managed toolkit snapshot when creating run request, and toolkits passed to engine must already be entered.
- Migration is needed to remove run-scoped fields from `ToolkitContext` or restrict them to session-stable use.
- Fields actually needed by run/turn handlers, such as `session_id`, `agent_id`, `interface_*`, and `check_stop`, may need to be explicitly added to `TurnContext` or per-turn handler context.
- `ScheduleToolkit` and subagent tool split into session-stable shell and per-turn handler factory.
- MCP/GitHub per-user credential lookup moves from resolve-time user capture to turn-time actor lookup.
- First turn does not wait for toolkit readiness. Toolkits still preparing should return `wait_ready`/loading prompt, and model call should be able to start immediately.
- Existing tests must verify that `__aenter__()` is called before first run, the same toolkit instance is reused in the next run of the same session, and `__aexit__()` is called exactly once on session termination.
