---
title: "Linearize Input Buffer Boundaries on the Session Row Lock"
created: 2026-07-12
tags: [architecture, backend, database, engine, concurrency, session, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: linearize-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0137-linearize-input-buffer-boundaries-on-session-row-lock.md"
---

# linearize-260712/ADR: Linearize Input Buffer Boundaries on the Session Row Lock

## Context

Sequential buffer preparation requires a deterministic boundary between accepting another input and starting or continuing a turn. Without a shared database serialization point, a producer can insert a new buffer after the worker observes an empty queue but before it claims the next turn. `FOR UPDATE SKIP LOCKED` also allows a concurrent processor to bypass a locked FIFO head and process a later row first.

Redis worker ownership reduces concurrency but is a lease without a database fencing token. FIFO and empty-boundary correctness must not depend solely on that external ownership assumption.

## Decision

Use the AgentSession row lock as the per-session input-queue linearization point.

Every input-buffer producer must:

1. lock the target AgentSession row with `SELECT ... FOR UPDATE`;
2. validate its producer-specific session and permission rules;
3. insert its input buffer and apply any required session run-state transition;
4. commit before sending a payload-free wake-up.

Normal follow-up input may still be accepted while a session is running. The lock is a serialization requirement, not an idle-only policy. Producers such as queued mailbox `send_message` retain their explicit no-wake and run-state semantics while still participating in the row-lock protocol.

The drain orchestrator processes one FIFO item at a time. For an atomic processor it locks the AgentSession row and the oldest buffer row, applies the processor result, and commits. It does not use `SKIP LOCKED` and never bypasses the durable FIFO head.

Long-running processors such as `create_git_worktree` must not hold the AgentSession database row lock across external Runtime operations. They atomically create or claim their durable action-execution state, release the transaction during external work, and reacquire the Session and source Buffer rows when committing their terminal preparation outcome. Their durable claim prevents another processor from executing the same head concurrently.

After the last item result, the orchestrator opens one final transaction and:

1. locks the AgentSession row;
2. checks again for the oldest pending buffer;
3. if another buffer exists, returns to processing;
4. if the queue is empty, atomically claims or continues the next turn when the folded TurnEffect permits it, or transitions the session to idle otherwise.

This final empty check and turn claim or idle transition are one database serialization boundary.

If a producer commits before the final boundary lock, the orchestrator observes and processes that buffer before turn claim. If the orchestrator commits turn claim first, a later producer's buffer belongs to a later between-turn boundary. Lock order defines the accepted ordering without relying on WebSocket or broker delivery order.

## Rejected Alternatives

### Keep `FOR UPDATE SKIP LOCKED`

A second processor could skip a locked FIFO head and prepare later input first if worker ownership overlaps during lease expiry or recovery.

### Use Redis ownership as the only mutex

Redis ownership is an operational routing lease and does not atomically serialize Postgres input acceptance with turn creation.

### Check queue emptiness and create the turn in separate transactions

A producer can commit between those operations, causing the worker to start a turn from a stale empty observation.

### Hold the Session row lock during long external actions

Runtime work can take seconds or minutes. Holding a database lock across that work would block input acceptance and unrelated session mutations and increase failure recovery cost.

## Consequences

- All buffer producers share one lock-ordering protocol.
- FIFO correctness no longer depends on `SKIP LOCKED` or Redis ownership exclusivity.
- Empty queue observation and turn claim become atomic relative to new input acceptance.
- Later input accepted after turn claim is intentionally deferred to the next boundary.
- Long-running processors require durable per-item execution claims and terminal commit logic.
- Repository tests must cover producer-versus-empty-boundary races, overlapping worker recovery, and FIFO head blocking.
- Existing producer services that read the session without locking must be migrated to the shared protocol.

## References

- [drain-260712/ADR: Drain Input Buffers Sequentially Before Turn Start](./drain-260712-drain-input-buffers-before-turn-start.md)
- [handle-260712/ADR: Handle Message Edits as Transactional Preparation](./handle-260712-handle-message-edits-as-transactional-preparation.md)
- [fold-260712/ADR: Fold Turn Eligibility with Failure Veto](./fold-260712-fold-turn-eligibility-with-failure-veto.md)
- [polymorphic-260712/ADR: Use Polymorphic Input Buffer Processors](./polymorphic-260712-polymorphic-input-buffer-processors.md)

## Migration provenance

- Historical source filename: `0137-linearize-input-buffer-boundaries-on-session-row-lock.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
