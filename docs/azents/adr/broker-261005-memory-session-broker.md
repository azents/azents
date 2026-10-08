---
title: "Redis-Free Single-Process Operation Decisions"
created: 2026-10-05
tags: [backend, broker, runtime, reliability]
document_role: primary
document_type: adr
snapshot_id: broker-261005
---

# Redis-Free Single-Process Operation Decisions

- Snapshot: `broker-261005`
- Requirements: [broker-261005/REQ](../requirements/broker-261005-memory-session-broker.md)

## ADR-D1. A co-located memory backend, retaining the Redis deployment

The requester selected single-process in-memory operation, not Redis-free
cross-process operation (REQ-1, REQ-4). Add an explicit Session backend selection
with the existing Redis default. Memory selection uses one application-owned
broker state and the existing memory implementations for related ephemeral
services. This is an implementation of the confirmed topology, not automatic
failover after a Redis failure.

The existing all-in-one process already shares AppContext and dependency
composition across API, Worker and Scheduler. Reuse that ownership boundary;
share the same Runtime coordination stores with the co-located Control server.
Independent API/Worker roots and reload children cannot share these objects and
therefore cannot serve this memory mode.

A process-local queue per role is rejected because it violates the confirmed
shared-state outcome. A distributed PostgreSQL broker is outside the request.
Redis mode retains its existing adapters and defaults without migration.

## ADR-D2. Memory remains ephemeral and preserves existing fences

Retain PostgreSQL execution authority and the current broker lease/heartbeat,
activity-generation and cutover-token acceptance rules (REQ-2, REQ-3; current
[Run Resume Spec](../spec/flow/run-resume.md)). Memory state has the same bounded
lifetimes and starts empty on process restart. Existing recovery emits routing
signals from durable work; memory contents never authorize durable completion.

No persistence format, schema migration, authorization bypass or replay authority
is introduced. A memory backend cannot provide distributed guarantees and is
explicitly restricted to the selected co-located process.
