---
title: "Ephemeral Redis Coordination Authority Requirements"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-08
tags: [architecture, backend, reliability, redis]
document_role: primary
document_type: requirements
snapshot_id: redis-260907
---

# Ephemeral Redis Coordination Authority Requirements

- Snapshot: `redis-260907`
- Document reference: `redis-260907/REQ`

## Problem

Azents defines Redis/Valkey as replaceable volatile coordination, but current Runtime connection generation allocation retains non-expiring Redis counters and current documentation requires those counters to survive. Replacing Redis with an empty instance can therefore reuse or regress fencing generations, conflict with durable connection history, reject new Runtime state, or let an old stream collide with newly issued authority. Reference deployment configuration also preserves Valkey data, which hides this failure mode, and some current documentation does not state the complete empty-store recovery contract.

## Primary Context

### Primary System Outcome

After Redis/Valkey becomes unavailable and is restored as a completely empty instance, Azents automatically resumes new work and reconciliation from durable authority without restoring any prior Redis key, stream, lock, cursor, counter, index, or live projection. Lost in-flight work fails closed and is never inferred as successful.

## Supporting Scenarios or Effects

- Runtime Provider and Runner clients reconnect after their prior volatile registrations disappear and receive authority that cannot collide with an earlier connection.
- Worker wake-up and ownership routing recover from durable Session and execution state after Redis signals and leases disappear.
- Runtime Transfer, interactive Terminal, live chat projection, External Channel locking, and other Redis-backed paths preserve their existing volatile or durable ownership boundaries.
- Operators and local developers can replace Valkey with an empty instance without a data-restore procedure.
- Provider enrollment rate limiting remains a best-effort abuse-control layer; resetting its active window does not grant or recreate credential authority.

## Goals

- Eliminate every correctness dependency on Redis persistence or retained keys.
- Preserve stale-writer and stale-stream fencing across empty-store replacement.
- Define one consistent failure, recovery, deployment, and documentation contract for all Redis-backed features.
- Add deterministic evidence that empty-store recovery works without manual repair.

## Non-Goals

- Keeping in-flight operations, live partials, Terminal replay, Pub/Sub delivery, or active leases available through a Redis outage or reset.
- Providing zero-downtime Redis failover or requiring Redis clustering, replication, persistence, or high availability.
- Removing Redis as the distributed coordination and notification implementation in this snapshot.
- Requiring exact continuity of the Provider enrollment rate-limit counter across Redis loss.
- Changing user-visible Runtime lifecycle, Terminal, transfer, chat, External Channel, or Scheduled Task behavior outside failure and recovery correctness.
- Rewriting implemented historical Requirements, ADRs, or Designs.

## Requirements

### REQ-1. Empty-store automatic recovery

Every Redis-backed capability must recover automatically after Redis is restored empty, without an operator recreating or seeding prior Redis state.

**Acceptance criteria**

- New admissible work can start after Redis recovery using only current durable authority and newly created volatile state.
- No startup, reconnect, reconciliation, cleanup, or authorization path requires an old Redis key, stream, lock, cursor, counter, or index.
- A missing Redis record is handled as lost volatile state, not as evidence that durable product state or external resources do not exist.

### REQ-2. Connection authority cannot be reused or regressed

Runtime Control-issued Provider and Runner connection authority must remain distinct from every previously issued authority for the same subject after Redis loss or replacement.

**Acceptance criteria**

- Runtime Provider and Runner clients do not choose their accepted connection authority.
- A newly accepted connection cannot reuse or regress to an authority that can be mistaken for an earlier connection of the same Provider or Runtime.
- Delayed messages, heartbeats, close handling, operation events, reports, and transfer results from a replaced connection cannot mutate or revoke newer authority.
- Empty Redis recovery does not conflict with durable Provider connection history or prevent current Runner state from becoming authoritative.

### REQ-3. Lost in-flight work fails closed

Redis loss must not convert unknown, partially delivered, or partially executed work into success or authorize it to continue under reconstructed state.

**Acceptance criteria**

- Lost Runtime operations, transfers, Terminal sessions, broker deliveries, live projections, locks, and leases are never inferred as completed successfully.
- Retry or reconciliation starts from durable intent and current authority rather than replaying an unknown side effect.
- Existing at-most-once, idempotency, cancellation, owner-generation, desired-generation, and durable terminal-result protections remain enforced.

### REQ-4. Durable state remains the recovery authority

Product state and recovery obligations must remain owned by their existing durable authorities independently of Redis contents.

**Acceptance criteria**

- PostgreSQL remains authoritative for Runtime desired/observed state, Provider identity and connection history, Session/mailbox/run state, External Channel ordering and leases, Scheduled Tasks, and durable results.
- Object storage remains authoritative only for objects already governed by durable product state or state-independent orphan cleanup rules.
- Worker, Runtime, file, and External Channel reconciliation can reconstruct required wake-ups or actions from durable state without restoring Redis.

### REQ-5. Best-effort enrollment rate limiting does not become credential authority

Provider enrollment rate limiting may lose its active counting window with Redis, while credential authorization and one-time exchange correctness remain durable and unaffected.

**Acceptance criteria**

- Redis reset may permit a fresh best-effort rate-limit window.
- A reset cannot make an invalid, expired, consumed, revoked, mismatched, or incorrectly bound grant exchangeable.
- Current documentation distinguishes the best-effort abuse-control limit from durable credential and binding authority.

### REQ-6. Deployment contract exposes volatile Valkey semantics

Azents-owned reference deployment and development configuration must not imply that Valkey data retention, persistent storage, replication, or HA is required for correctness.

**Acceptance criteria**

- Reference local/test Valkey configuration can be destroyed and recreated empty without a documented restore step.
- Operator documentation states that Redis/Valkey persistence and retained data are unnecessary and must not be used as a recovery prerequisite.
- Durable PostgreSQL, object-storage, and Runtime Workspace persistence remain clearly distinct from volatile Redis/Valkey coordination.

### REQ-7. Current documentation has one consistent authority model

Living Specs and current operator documentation must consistently describe Redis/Valkey as replaceable volatile coordination and identify the durable recovery authority for each affected flow.

**Acceptance criteria**

- Runtime Control no longer requires Redis-retained connection generation counters.
- Broker/run recovery, live projections, Runtime Transfer, Terminal, External Channel locks, enrollment rate limiting, and deployment behavior state their empty-store outcome.
- Implemented historical Requirements, ADRs, and Designs remain unchanged and are treated as historical context rather than current behavior authority.

### REQ-8. Empty-store behavior is deterministically verified

Required automated verification must exercise Redis state loss at the correctness boundaries that could otherwise depend on retained state.

**Acceptance criteria**

- Tests replace or clear Redis between earlier and later connection registrations and prove stale authority cannot collide with the recovered connection.
- Tests prove new work and reconciliation resume without seeding old Redis data.
- Tests cover fail-closed treatment of lost in-flight state and the best-effort reset behavior of enrollment rate limiting.
- Deployment validation proves the reference Valkey configuration has no required persistence contract.

## Fixed Constraints

- Runtime Control, not Runtime Provider or Runner, issues accepted connection authority; clients only return the accepted value in later protocol messages.
- Redis failure may make affected service paths temporarily unavailable until Redis is restored and normal reconnect or reconciliation occurs.
- Existing public APIs and protocol message shapes remain compatible unless a later ADR demonstrates that an interface change is unavoidable.
- PostgreSQL and object storage remain available durable dependencies according to their current domain ownership.
- Redis-backed and in-memory implementations of the same coordination contract must preserve equivalent observable correctness semantics.
- No backward-compatibility reader or fallback may preserve the incorrect Redis-persistence authority after migration.
- Git-tracked artifacts and public-safe technical documentation remain in English.

## Open Assumptions

- The change has no intentional user-facing UI or workflow effect beyond bounded interruption followed by automatic recovery.
- Existing durable Runtime, Session, External Channel, file, and Scheduled Task state contains sufficient authority to reconstruct all required post-reset work once connection-generation authority is corrected.
- Operational metrics and logs may expose bounded reset/reconnect outcomes without storing message content, credentials, Terminal bytes, file bytes, or raw provider payloads.

## Confirmation

Confirmed by the requester on 2026-09-07 before ADR and design decisions began.
