---
title: "ADR-0020: Phase 2 — Durable Lifecycle Workflow + Lease Token Discussion"
created: 2026-04-16
tags: [backend, engine, infra, architecture]
---

<!-- Design document, implemented: phase2-durable-lifecycle-workflow.md -->

# ADR-0020: Phase 2 — Durable Lifecycle Workflow + Lease Token

> 📌 **Related design document** (implemented): [phase2-durable-lifecycle-workflow.md](../design/phase2-durable-lifecycle-workflow.md)
>
> This document records design-stage discussion. See the linked document for the final design and implementation.

## Overview

Phase 1 (#2609) established DB-based activity tracking and lifecycle hooks. Phase 2 replaces the current simple 60-second poll+delete loop with a **deadline-driven lifecycle loop + DB lease token** to improve correctness, failure recovery, and scalability.

Prerequisites: #2608 (research), #2609 (Phase 1)
Vercel reference: `apps/web/lib/sandbox/lifecycle.ts`, `lifecycle-kick.ts`

## Current State After Phase 1

- `AgentHomeSandboxManager._cleanup_loop()` — sleep 60 seconds → `find_idle_agent_ids` → delete.
- `conversation_sessions.last_activity_at` — DB-based idle judgment, source of truth.
- Lifecycle hooks — AFTER_START / BEFORE_STOP / ON_IDLE_TIMEOUT.
- Single EngineWorker process; multi-worker HA is future work.

**Problems**:

- 60-second polling creates up to 59 seconds of error. This is acceptable for a 30-minute threshold but inefficient.
- No crash recovery. After worker restart, lifecycle judgment for existing Pods resumes only after 60 seconds.
- No lease. In future multi-worker mode, two workers could clean up the same agent at the same time.
- Activity refresh does not update deadline immediately. If a user sends a message at 29m 59s, cleanup can still happen one second later.

---

## Discussion Points and Decisions

### D1. Lifecycle state storage location

**Background**: Where should lease token and lifecycle state live?

**Options**:

- **A**. Add two columns to the `agents` table: `lifecycle_run_id`, `lifecycle_state`.
- **B**. Separate `agent_lifecycle_leases` table.
- **C**. Redis sorted set.

**Decision: A — `agents` table**

**Rationale**:

- Agent count is small, under 100 concurrent, and lifecycle write frequency is low: once per state transition, not heartbeat.
- A separate table adds join and management cost with little benefit.
- Redis would create a second state store and consistency problems. Continue Phase 1's philosophy of DB as the single source.
- `agents` is a cold object, but lifecycle writes happen only a few times over the agent lifecycle, such as start, activity refresh, and stop. This is negligible compared with per-message touches on `conversation_sessions`.

### D2. Per-agent individual task vs enhanced global loop

**Background**: There is currently one global loop. Switching to per-agent tasks wakes each agent exactly at its deadline but creates N concurrent tasks.

**Options**:

- **A**. Per-agent asyncio task, for example 100 agents = 100 tasks.
- **B**. Enhanced global loop — sleep until `MIN(deadline)`, then batch evaluate.
- **C**. Keep status quo, 60-second polling.

**Decision: B — deadline-driven global loop**

**Rationale**:

- Memory/CPU for 100 asyncio tasks is negligible, but task management complexity—creation, cancellation, tracking—is high.
- In a global loop, sleep until `MIN(next_deadline)` and evaluate only due agents when awake. This improves accuracy while staying simple.
- Keep a 60-second cap as a safety net. Worst-case error remains 60 seconds, but most work happens at the exact deadline.
- When moving to Phase 3, such as Temporal or another durable workflow, only this loop needs replacement.

**Implementation sketch**:

```python
async def _lifecycle_loop(self) -> None:
    while True:
        next_wake = await self._compute_next_deadline()
        sleep_secs = min(
            (next_wake - now()).total_seconds() if next_wake else 60.0,
            60.0,  # safety cap
        )
        try:
            await asyncio.wait_for(self._activity_event.wait(), timeout=max(sleep_secs, 1.0))
            self._activity_event.clear()
        except asyncio.TimeoutError:
            pass
        await self._evaluate_lifecycle()
```

### D3. Lease token mechanism

**Background**: Lease is needed to prevent concurrent cleanup and support crash recovery.

**Options**:

- **A**. DB compare-and-set (`agents.lifecycle_run_id`).
- **B**. Redis Lua, reusing the SchedulerWorker pattern.
- **C**. In-memory lock inside the process.

**Decision: A — DB compare-and-set**

**Rationale**:

- DB is already the source of truth for idle judgment. Keeping the lease there allows judgment + claim in one query.
- Redis Lua is proven in SchedulerWorker, but Agent Home lifecycle is DB-centered by design, consistent with Phase 1.
- In-memory lock is lost on restart and cannot support crash recovery.

**Compare-and-set SQL**:

```sql
UPDATE agents
SET lifecycle_run_id = :new_run_id
WHERE id = :agent_id
AND (lifecycle_run_id IS NULL OR lifecycle_run_id = :old_run_id)
RETURNING id;
```

### D4. Activity refresh → deadline recalculation

**Background**: When a user message arrives, the idle deadline should extend. The current loop may be sleeping for 60 seconds, so it is not reflected immediately.

**Options**:

- **A**. Wake the loop immediately with `asyncio.Event`.
- **B**. Cancel and recreate task.
- **C**. Let DB polling handle it within 60 seconds.

**Decision: A — asyncio.Event**

**Rationale**:

- One Event can immediately wake the sleeping loop and recalculate deadline, giving zero error.
- Cancel/recreate causes excessive churn.
- DB polling with 60 seconds is the same as Phase 1 and does not meet Phase 2's improvement goal.

**EngineWorker integration**:

```python
# after _touch_session_activity
await self.sandbox_manager.notify_activity(agent_id)
```

### D5. Crash recovery

**Background**: Detect stale leases and recover after worker crash.

**Options**:

- **A**. `lifecycle_run_id` + claimed_at timestamp with 120-second grace period.
- **B**. Separate heartbeat table.
- **C**. No recovery; 60-second polling eventually covers it.

**Decision: A — lifecycle_run_id + grace period**

**Rationale**:

- Add `agents.lifecycle_claimed_at: datetime`. Record NOW() when claiming lease.
- On worker startup, agents with `lifecycle_claimed_at < NOW() - 120s` are stale → clear → re-kick.
- Separate table is overkill. No recovery contradicts the Phase 2 goal.
- 120-second grace matches the Vercel pattern. Compared with a 30-minute threshold, it is about 0.4%, sufficiently conservative.

### D6. Lifecycle state values

**Decision**: `active` / `stopping` / NULL, a 3-state model.

- `NULL`: not monitored by lifecycle, before allocation or after deletion.
- `active`: Agent Home is allocated and monitored by lifecycle loop.
- `stopping`: cleanup is in progress, including hook dispatch + delete.

Intermediate states such as `idle_pending` are unnecessary because idle judgment is immediately derived from the DB query and does not need to be stored as state.

### D7. Grace period value

**Decision**: 120 seconds, same as Vercel. Use `LIFECYCLE_STALE_GRACE_SECS` config constant.

### D8. Phase 1 hook compatibility

**Decision**: Hook interface does not change. Only dispatch timing changes:

- `AFTER_START`: same as before, after get_or_allocate cache miss.
- `ON_IDLE_TIMEOUT` / `BEFORE_STOP`: move from existing `_cleanup_idle` to new `_evaluate_lifecycle`.
- Phase 2 changes **when**, not **what**.

### D9. Migration strategy

**Decision**: Add three nullable columns to `agents`:

- `lifecycle_run_id: str | None`
- `lifecycle_state: str | None`
- `lifecycle_claimed_at: datetime | None`

No backfill is required because NULL means untracked. Downgrade simply drops the columns.

### D10. EngineWorker integration

**Decision**:

- After `EngineWorker._touch_session_activity`, call `sandbox_manager.notify_activity(agent_id)`.
- `notify_activity` calls `_activity_event.set()` → loop wakes immediately → deadline recalculated.
- Agent ID is extracted from `SessionMessage.agent_id`, which is already available.

---

## Decision Summary Table

| # | Point | Decision |
|---|---|---|
| D1 | Storage location | `agents` table, 3 columns |
| D2 | Loop structure | Deadline-driven global loop |
| D3 | Lease mechanism | DB compare-and-set |
| D4 | Activity refresh | Wake loop with asyncio.Event |
| D5 | Crash recovery | lifecycle_claimed_at + 120s grace |
| D6 | State values | active / stopping / NULL |
| D7 | Grace period | 120 seconds |
| D8 | Hook compatibility | no interface change |
| D9 | Migration | add 3 nullable columns |
| D10 | Worker integration | notify_activity → Event.set() |
