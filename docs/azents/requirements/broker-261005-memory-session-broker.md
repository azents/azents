---
title: "Redis-Free Single-Process Operation Requirements"
created: 2026-10-05
implemented: 2026-10-05
tags: [backend, broker, runtime, reliability]
document_role: primary
document_type: requirements
snapshot_id: broker-261005
---

# Redis-Free Single-Process Operation Requirements

- Snapshot: `broker-261005`
- Document reference: `broker-261005/REQ`

## Problem

Single-process operation still constructs a Redis Session broker and Redis-only
coordination dependencies. Existing memory adapters do not cover the Session
broker, so a Redis service remains necessary even when all roles are co-located.

## Primary System Outcome

One process runs the API and Worker with shared memory-backed ephemeral state,
without a Redis service, while PostgreSQL retains durable execution authority.

## Supporting Scenarios or Effects

- The existing separate-process Redis deployment continues unchanged.
- Restart recovery treats memory state as disposable, not as durable work history.

## Goals

- Deliver the implementation and working composition, not only documentation.
- Preserve Session routing, activity, ownership, cutover and recovery guarantees.

## Non-Goals

- Redis-free distributed API/Worker operation or a PostgreSQL distributed broker.
- Changing authorization, model behavior, database schema or live infrastructure.

## Requirements

### REQ-1. Redis-free co-located execution

A single-process configuration must start and process Session work without
connecting to Redis. Existing co-located API, Worker and Scheduler roles share
one ephemeral state lifetime. Runtime coordination in that process remains usable.

**Acceptance criteria**

- API-produced wake and stop signals reach the co-located Worker.
- Session event projection and Runtime coordination do not construct Redis clients.
- No Redis URL needs to be supplied for this configuration.

### REQ-2. Preserve Session broker behavior

Wake/stop routing, live-owner-only mailbox notifications, sticky ownership,
heartbeat, generation-fenced activity, purge and exact-token cutover barriers
retain their current behavioral guarantees within one process.

**Acceptance criteria**

- Concurrent callers cannot steal a live owner or overwrite newer activity.
- Purge removes Session ephemeral state; barriers prevent ownership acquisition
  until exact release or expiry.

### REQ-3. Keep durable recovery authoritative

Memory loss must not imply that durable work completed. The existing PostgreSQL
recovery path must be able to wake work through a fresh, empty memory broker.

**Acceptance criteria**

- Fresh process-local state accepts recovery wake-ups without retained keys.
- Existing execution-generation, cancellation and recovery contracts are unchanged.

### REQ-4. Bound memory operation to one process

Memory state must not be silently presented as cross-process coordination.
Existing Redis-mode defaults and behavior remain supported.

**Acceptance criteria**

- Reload/independent-role configurations that split required memory owners fail
  before serving work.
- Explicit Redis-mode composition still creates the existing Redis adapters.

## Fixed Constraints

- The requester explicitly requires a memory implementation for single-process use.
- Redis failure does not trigger an implicit backend change.
- No live deployment or PR merge is authorized by this implementation request.

## Open Assumptions

None that block the confirmed single-process implementation scope.

## Confirmation

The requester confirmed the single-process memory requirement and explicitly
instructed implementation on 2026-10-05. No additional requirement interview or
approval pause is requested for this bounded correction.
