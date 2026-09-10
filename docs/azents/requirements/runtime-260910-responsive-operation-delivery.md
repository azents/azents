---
title: "Responsive Runtime Operation Delivery Requirements"
created: 2026-09-10
updated: 2026-09-10
implemented: 2026-09-10
tags: [runtime, performance, reliability, observability]
document_role: primary
document_type: requirements
snapshot_id: runtime-260910
---

# Responsive Runtime Operation Delivery Requirements

- Snapshot: `runtime-260910`
- Document reference: `runtime-260910/REQ`

## Problem

Runtime operations can complete promptly in the Runner while the Worker remains
CPU-saturated and delays observing the completed reply for several seconds. The
same failure domain can amplify coordination traffic, obscure the component that
introduced the delay, and leave a disconnected Runner retrying with unusable
connection authority.

## Primary Context

### Primary System Outcome

Concurrent Runtime operations remain responsive without coordination waiting
consuming a Worker CPU core, while preserving existing operation ordering,
deadline, cancellation, fencing, and recovery behavior.

## Supporting Scenarios or Effects

- Operators can distinguish Runner execution time from reply-delivery and Worker
  scheduling delay.
- Deployments can add Worker capacity without changing the Runtime protocol.
- A Runner reconnects with current authority after its prior connection authority
  becomes invalid.

## Goals

- Remove Worker CPU growth caused by waiting for Runtime operation replies.
- Preserve reliable, bounded foreground Runtime tool completion.
- Make reply-delivery and Worker scheduling latency observable.
- Keep the Worker deployment horizontally configurable.
- Recover Runner connectivity after connection authority changes.

## Non-Goals

- Making Runtime coordination durable or available when Redis is lost.
- Changing model-visible Runtime tool names, arguments, results, or error
  semantics.
- Replacing Redis as the production coordination implementation.
- Automatically merging or applying deployment changes to a live environment.

## Requirements

### REQ-1. Efficient bounded reply delivery

Waiting for Runner operation replies must not generate work at a fixed high
frequency while no reply is available.

**Acceptance criteria**

- An idle reply waiter consumes no repeated coordination read/write cycle.
- A newly appended reply wakes an eligible waiter without a user-visible polling
  interval delay.
- Concurrent Runtime operations do not create a self-amplifying Worker CPU loop.

### REQ-2. Existing operation semantics remain intact

The reply-delivery change must preserve the existing Runtime operation contract.

**Acceptance criteria**

- Already-appended replies are observed in cursor order.
- Deadlines still produce the existing timeout failure path.
- User and task cancellation remain bounded and request Runner cancellation.
- Generation fencing and final-event authority remain unchanged.
- Redis and in-memory coordination provide equivalent observable behavior.

### REQ-3. Read-side coordination remains non-mutating

Observing or waiting for a reply must not extend stream lifetime or otherwise
mutate coordination state.

**Acceptance criteria**

- Reply stream retention is refreshed by authoritative writes rather than empty
  reads.
- A long-running operation within its supported deadline retains enough
  coordination state to complete.
- Redis loss continues to fail closed under the existing optional coordination
  policy.

### REQ-4. Delivery and scheduling latency are observable

Operators must be able to identify where Runtime operation latency accumulated
without using request identifiers as metric labels.

**Acceptance criteria**

- Metrics expose active reply waiting, wait duration and outcome, and delayed
  Worker observation of Runner replies using bounded-cardinality dimensions.
- Worker event-loop delay is observable independently of Runner execution time.
- Structured logs retain request-scoped evidence needed for targeted correlation.

### REQ-5. Worker capacity is configurable

The deployment must permit operators to run more than one Worker replica without
editing the rendered Deployment.

**Acceptance criteria**

- The Helm chart exposes a Worker replica setting with a backward-compatible
  default.
- Rendering tests cover the default and an explicit multi-replica value.
- A consumer deployment can opt into additional Worker capacity through values.

### REQ-6. Runner reconnect uses current authority

A Runner whose connection authority is rejected must be able to obtain and use
current authority rather than retrying the same unusable credential indefinitely.

**Acceptance criteria**

- Reconnect reacquires the currently authorized Runner credential.
- Stale credential rejection and credential reacquisition failure are
  distinguishable in operational evidence.
- Recovery does not weaken runtime identity or generation fencing.

## Fixed Constraints

- Redis remains optional and the in-memory implementation remains behaviorally
  equivalent for standalone, development, and tests.
- Blocking coordination operations must remain cancellable and must not depend on
  a Redis socket I/O timeout.
- Automatic Redis command retries remain disabled for non-idempotent coordination
  operations.
- Metrics must avoid request, operation, Runtime, Session, and Agent identifiers as
  labels.
- Live infrastructure changes stop at reviewed pull requests until separately
  approved for merge and synchronization.

## Open Assumptions

- The existing one-hour reply stream retention exceeds supported foreground
  operation deadlines and their completion grace.
- Existing Session ownership and broker coordination permit multiple Worker
  replicas; implementation will verify that assumption before enabling a
  multi-replica consumer value.

## Confirmation

Confirmed by the requester on 2026-09-10 before ADR and design decisions began.
