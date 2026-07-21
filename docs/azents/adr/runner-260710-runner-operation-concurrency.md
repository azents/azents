---
title: "Session-Scoped Runner Operation Concurrency"
created: 2026-07-10
tags: [architecture, backend, runtime, performance, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: runner-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0102-session-scoped-runner-operation-concurrency.md"
---
# runner-260710/ADR: Session-Scoped Runner Operation Concurrency

## Context

A Runtime Runner is shared by multiple Agent Sessions. The current Runner applies one `max_concurrent_operations` value to all operations in the Runtime, so concurrent Sessions contend for the same four execution slots. This makes the configured value behave as a Runtime-wide limit even though it was intended to bound each Session independently. Long-running process operations can therefore delay short file operations and Session initialization work from unrelated Sessions.

## Decision

### runner-260710/ADR-D1. Apply a per-Session limit of 10 and a Runtime-wide limit of 50

Runner operation concurrency will be limited on two levels:

- Each Agent Session may execute at most 10 Runner operations concurrently.
- One Runtime Runner may execute at most 50 Runner operations concurrently across all Sessions.

The default values are 10 per Session and 50 per Runtime. The Runtime-wide limit is a safety ceiling rather than the primary fairness boundary. A Session that reaches its own limit must not consume additional execution capacity while other Sessions remain eligible.

### runner-260710/ADR-D2. Schedule eligible Session queues in round-robin order

The Runner will maintain Session-scoped pending operation queues and select eligible Sessions in round-robin order. A Session is eligible while it has pending operations, has fewer than 10 active operations, and the Runtime has fewer than 50 active operations.

The scheduler must skip temporarily ineligible Sessions without blocking operations from other Sessions. Completion of an active operation makes its Session eligible again and wakes scheduling. FIFO ordering is preserved within each Session queue, but there is no single Runtime-wide FIFO ordering guarantee across Sessions.

### runner-260710/ADR-D3. Use a bounded system queue for operations without a Session owner

Every Runner operation request carries an optional common `owner_session_id`. Session-owned callers must provide their Agent Session ID. Agent-level operations that do not belong to a Session, including Agent Workspace file management, Project catalog refresh, and pre-Session Git ref preview, use one Runtime-scoped system queue.

The system queue participates in the same round-robin scheduling as Session queues and may execute at most 10 operations concurrently. Its operations count toward the Runtime-wide limit of 50. Client methods require callers to pass `owner_session_id` explicitly as a nullable value so ownership omission is intentional rather than implicit.

### runner-260710/ADR-D4. Share one Session limit across ordinary operation types

Process, file, and Git operations share the same 10-operation Session limit and the same 50-operation Runtime limit. The first implementation does not reserve or partition capacity by operation type. Per-type sub-limits may be introduced later only if production evidence shows persistent same-Session interference.

### runner-260710/ADR-D5. Keep termination and cleanup available outside normal operation capacity

Session termination and Runner shutdown cleanup are control-plane work rather than ordinary user operations. They must not wait behind a saturated ordinary operation queue. The Runner executes termination and mandatory cleanup through a dedicated control path with a default concurrency of 4. These actions do not consume ordinary Session or Runtime execution slots. The control-path limit is configurable and must be positive.

### runner-260710/ADR-D6. Bound pending queues and fail admission explicitly

The Runner bounds pending work to 100 operations per Session or system queue and 1,000 operations per Runtime. Admission occurs directly at the Runner transport receive boundary; the existing unbounded intermediate operation queue is removed. The receiver atomically admits work into owner queues or returns an explicit final `operation_queue_full` error. Pending operations retain their end-to-end deadlines; expired work returns `operation_timeout` without consuming an execution slot. Cancellation and generation fencing invalidate matching pending work.

### runner-260710/ADR-D7. Propagate ownership across foreground and background operations

Foreground operations use the invoking Agent Session ID. Background operations use their durable parent Session ID. Agent-level operations deliberately use the system queue. Subagent Sessions are independent Agent Sessions and receive independent per-Session limits.

### runner-260710/ADR-D8. Make limits configurable and observable

Runner configuration exposes execution and pending limits with validated defaults: 10 per Session, 10 for the system queue, 50 per Runtime, 100 pending per owner, 1,000 pending per Runtime, and 4 control-path operations. Structured diagnostics distinguish queue wait from execution time and expose pending, active, and rejected operation counts with request, Runtime, generation, and ownership correlation.

### runner-260710/ADR-D9. Use a coordinated internal protocol transition

`owner_session_id` moves to the common Runner operation request and envelope. Process-specific duplicate ownership fields are removed. Control, the shared runtime-control library, and Runner move together without a legacy fallback path.

### runner-260710/ADR-D10. Verify fairness and saturation behavior

Tests cover dual-limit accounting, owner FIFO order, cross-owner round-robin scheduling, the system queue, admission failure, deadline expiry, cancellation, generation changes, and termination during saturation. Integration tests verify gRPC ownership propagation. E2E verification runs at least five Sessions against one Runtime and confirms that one Session backlog does not block another Session's short operation.

Skill projection deduplication and singleflight remain a separate optimization.

## Consequences

- Five active Sessions can each use their full default allocation of 10 operations when the Runtime has sufficient capacity.
- A single Session cannot occupy more than 20% of the default Runtime-wide execution capacity.
- Runner operations must carry a Session ownership identity that is available to the Runner scheduler.
- The Runner needs scheduling behavior that enforces both limits rather than one global active-task count.
- Runtime-wide resource consumption can increase substantially from the current maximum of four concurrent operations, so queue depth, active counts, and operation latency require explicit observability.

## Migration provenance

- Historical source filename: `0102-session-scoped-runner-operation-concurrency.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
