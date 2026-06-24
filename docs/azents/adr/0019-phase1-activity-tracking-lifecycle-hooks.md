---
title: "ADR-0019: Phase 1 — Separate Activity Tracking and Introduce Lifecycle Hook Interface Discussion"
created: 2026-04-16
tags: [backend, engine, infra, architecture]
---

<!-- Design document, implemented: phase1-activity-tracking-lifecycle-hooks.md -->

# ADR-0019: Phase 1 — Separate Activity Tracking and Introduce Lifecycle Hook Interface

> 📌 **Related design document** (implemented): [phase1-activity-tracking-lifecycle-hooks.md](../design/phase1-activity-tracking-lifecycle-hooks.md)
>
> This document records design-stage discussion. See the linked document for the final design and implementation.

## Overview

This is **Phase 1, the lowest-risk foundation work**, from the four-stage roadmap derived from the [#2608 Vercel Open Agents research report](https://github.com/azents/azents/issues/2608#issuecomment-4254059615). The goal is to create clean *connection points* for later phases such as Git diff backup, durable workflow, and snapshot hibernation.

**Goals**:

1. Make Agent Home idle judgment reflect **only meaningful user activity**.
2. Explicitly expose lifecycle hook points for Agent Home.

This document is the output of Phase 1-1.5 from the autonomous `feature-design` skill.

---

## Current State Summary

**Current activity tracking** (`python/apps/nointern/src/nointern/runtime/sandbox/agent_home_manager.py`):

- `AgentHomeSandboxManager.get_or_allocate()` calls `AgentHomeClient.update_last_used(agent_id)` **on every call** at L99, L108, and L184.
- `update_last_used` is implemented separately by `DockerAgentHomeClient` and `K8sAgentHomeClient`, using an in-memory dict or container label.
- A 60-second `_cleanup_loop()` calls `_cleanup_idle()` → `list_idle_agents(threshold)`, and idle judgment is delegated to the client.
- Default idle threshold: `1800.0` seconds, or 30 minutes.

**Problems**:

- `get_or_allocate()` is called for every session message, so calls from probes, health checks, and RESUME also get recorded as activity.
- On process restart, in-memory tracking is lost, while only container labels remain. Persistence is partial.
- Activity is distributed across client backends, weakening testability, observability, and policy consistency.

**Current lifecycle hooks**:

- `AgentHomeClient` protocol only has `ensure_ready`, `exec`, `write_file`, `read_file`, and `delete_agent`.
- Lifecycle events are implicit inside manager call flow.
- There is no official point to attach later phases such as state capture, notification, or metric emission.

---

## Discussion Points and Decisions

### D1. Storage unit for `last_activity_at`

**Background**: Agent Home is persistent **per agent**, but activity happens **per session**. Where should the column live to make "MAX(last_activity) per agent" clean?

**Options**:

- **A**. `agents.last_activity_at` — store directly at agent level.
- **B**. `conversation_sessions.last_activity_at` — store on session; aggregate by agent with JOIN.
- **C**. Both.

**Decision: B — only on conversation_sessions**

**Rationale**:

- Agent is a long-lived domain object that is not deleted often, while session is the true owner of activity. When a session ends, its activity also stops being meaningful.
- The `agents` table is a relatively cold configuration object. Pushing lifecycle updates into it mixes write pressure with settings changes.
- If agent-level aggregation is needed, one query with `MAX(last_activity_at) GROUP BY agent_id` is enough.
- If future agent-level activity policy is needed, derive it later with a materialized view or trigger.

### D2. Events counted as activity

**Background**: "Meaningful" needs a definition. Currently every `get_or_allocate` call counts as activity.

**Options**:

- **A**. Every `SessionMessage` received by Redis broker.
- **B**. `SessionMessage` except `SessionMessageKind.RESUME`.
- **C**. Explicit allowlist — UserInput only.

**Decision: B — every SessionMessage except RESUME**

**Rationale**:

- Current `SessionMessage` mostly originates from user utterances. Only RESUME is for internal system re-enqueue (`engine.py:1434`).
- Switching to an allowlist can happen later when probes are introduced. There is no probe today.
- If RESUME is not excluded, every worker restart resets the idle timer and defeats the 30-minute policy.

**Update point**:

- Before or after `SessionRunner.enqueue()` (`engine.py:1122`) under condition `SessionMessage && kind != RESUME`.
- More specifically, handle in the EngineWorker dispatch path before L280 `runner.enqueue(message)`.

**Excluded**:

- Redis lock TTL refresh (`renew_session_ttl` in broker.py).
- State polling / health check.
- `SessionMessageKind.RESUME` re-enqueue.

### D3. Idle judgment source

**Background**: Where should AgentHomeManager decide "which agents are idle"?

**Options**:

- **A**. Keep `AgentHomeClient.list_idle_agents(threshold)` and let client keep internal tracking.
- **B**. Manager queries DB with `MAX(last_activity_at) GROUP BY agent_id WHERE MAX < NOW() - threshold`; client only performs `delete_agent`.
- **C**. Combine both with AND: DB idle AND client idle.

**Decision: B — Manager decides from DB**

**Rationale**:

- Client implementations such as Docker/K8s are freed from activity tracking responsibility and only manage container lifecycle.
- A single SQL query becomes the truth source, improving testability, observability, and policy consistency.
- Remove `update_last_used` / `list_idle_agents` from protocol. This is a breaking change, but it should be handled in Phase 1.
- Option C appears conservative, but disagreement between two sources creates a debugging nightmare and should be avoided.

**Query draft**:

```sql
SELECT agent_id, MAX(COALESCE(last_activity_at, updated_at, created_at)) AS last_act
FROM conversation_sessions
WHERE agent_id = ANY(:agent_ids)
GROUP BY agent_id
HAVING MAX(COALESCE(last_activity_at, updated_at, created_at)) < NOW() - :threshold::interval;
```

- `:agent_ids` comes from the manager's current cached agent list.
- `COALESCE` keeps existing rows safe during migration when `last_activity_at` may be NULL.

### D4. Cleanup interval / idle threshold

**Background**: Current values are 60-second polling and 30-minute threshold. Keep or change?

**Decision: keep 60-second polling and 1800-second threshold**

**Rationale**: Phase 1 is foundation work. Parameter tuning should be separated into a later tuning phase after DB-based judgment in D3 is stable.

### D5. Migration backfill value

**Background**: Initial value for `last_activity_at` on existing rows.

**Options**:

- **A**. `NULL`, no special handling.
- **B**. `updated_at`, the current row's latest recorded timestamp.
- **C**. `NOW()`, the migration time.

**Decision: B — backfill from existing `updated_at`** with `UPDATE ... SET last_activity_at = updated_at` in migration.

**Rationale**:

- A can be handled in idle queries with `COALESCE`, but future triggers/dashboards would need to handle NULL carefully.
- C disguises already-idle sessions as "just active," violating policy.
- B is the most reasonable approximation of existing activity time. `updated_at` can react to non-activity events such as title changes, but it does not wrongly make something look older.

### D6. Lifecycle Hook registration method

**Background**: How should hook handlers be injected?

**Options**:

- **A**. Add `hooks: Sequence[LifecycleHookHandler]` argument to `AgentHomeSandboxManager.__init__` through DI.
- **B**. Register globally through Manager class attribute / registry.
- **C**. Override through `AgentHomeClient` subclass.

**Decision: A — constructor DI**

**Rationale**:

- NoIntern generally uses FastAPI DI + `deps.py`; this is consistent.
- Global registry makes test isolation difficult.
- Client subclassing ties lifecycle logic to backends such as Docker/K8s and pollutes boundaries.

### D7. Hook handler protocol

**Background**: Callable signature.

**Decision**:

```python
class LifecycleHookHandler(Protocol):
    async def __call__(self, event: LifecycleEvent) -> None: ...
```

- `LifecycleEvent` is a dataclass; see D8.
- Both Python functions and class instances can be registered.
- Async only, matching the manager's async context.

### D8. Hook event payload

**Background**: Data structure passed to hooks.

**Decision**:

```python
class LifecycleEventType(enum.StrEnum):
    AFTER_START = "after_start"
    BEFORE_STOP = "before_stop"
    ON_IDLE_TIMEOUT = "on_idle_timeout"

@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    type: LifecycleEventType
    agent_id: str
    reason: str                         # e.g. "cache_miss_allocation", "idle_cleanup", "explicit_delete"
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

**Rationale**:

- Frozen dataclass + slots gives type safety and low cost.
- `reason` distinguishes context within the same event type, such as cleanup vs explicit delete.
- `metadata` leaves room for extension; Phase 1 defaults to an empty dict.

### D9. Hook failure policy

**Background**: What happens if a handler raises an exception?

**Decision**: default to **log & swallow**, isolating each handler. The only special case is `CancelIdleTimeout` from `on_idle_timeout`, which skips cleanup.

**Rationale**:

- Phase 1 hook consumers are likely optional, such as external notification or backup. If hook failure breaks manager lifecycle, blast radius is too large.
- Even if future state-capture in `before_stop` fails, delete should still proceed. A stronger `before_stop` policy can be reconsidered in a later phase.
- `on_idle_timeout` needs an intentional cancel mechanism, for example "important work is running now, so this is not idle." Use a dedicated exception.

### D10. `on_idle_timeout` cancel mechanism

**Decision**: dedicated exception.

```python
class CancelIdleTimeout(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
```

**Rationale**: Return-value based designs create ambiguous rules such as "do all handlers need to return cancel?" Exceptions naturally express first-cancel-wins semantics and make it easy to log the `reason`.

---

## Decision Summary Table

| # | Point | Decision |
|---|---|---|
| D1 | `last_activity_at` location | conversation_sessions |
| D2 | Activity event | SessionMessage except RESUME |
| D3 | Idle judgment | Manager DB query |
| D4 | Interval / threshold | keep 60s / 1800s |
| D5 | Backfill | copy `updated_at` |
| D6 | Hook registration | constructor DI |
| D7 | Handler protocol | async callable |
| D8 | Event payload | `LifecycleEvent` dataclass + `reason` |
| D9 | Failure policy | log & swallow with isolation |
| D10 | Cancel mechanism | `CancelIdleTimeout` exception |

---

## Tracking / Follow-up

- The discussion document acts as a **trace** of the design decisions. Later Phase 3, snapshot hibernation, will revisit D9's "strong before_stop" policy.
- Phase 2 Git diff backup is expected to be the first consumer of the `before_stop` handler.
- Phase 3 durable lifecycle workflow will consume D3's DB-based judgment as-is.
