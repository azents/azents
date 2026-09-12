---
title: "Isolated Runtime Operation Reply Streams Requirements"
created: 2026-09-12
updated: 2026-09-12
tags: [runtime, performance, reliability]
document_role: primary
document_type: requirements
snapshot_id: runtime-260912
---

# runtime-260912/REQ: Isolated Runtime Operation Reply Streams

- Snapshot: `runtime-260912`
- Document reference: `runtime-260912/REQ`

## Problem

Reply history retained for earlier Runtime operations can increase the work required
to observe a newly dispatched operation. A long-lived connection generation must not
make later Provider commands, Runner operations, or Runtime Transfers progressively
slower.

## Primary Context

### Primary System Outcome

The coordination work required to observe one newly dispatched operation remains
proportional to that operation's own reply events rather than the completed operation
history retained for the same connection generation.

## Supporting Scenarios or Effects

- Concurrent operations keep independent reply observation and cursor ordering.
- A rolling deployment can resume an admitted operation through the reply stream
  identity already recorded in its operation metadata.
- Operators retain bounded evidence when an event does not match the waiting request.

## Goals

- Prevent retained reply history from causing progressively slower Runtime operations.
- Apply the same isolation rule to Provider commands, ordinary Runner operations, and
  Runtime Transfer dispatches.
- Preserve deadline, cancellation, resume, generation-fencing, and retention behavior.

## Non-Goals

- Changing generation-scoped request delivery or consumer-group semantics.
- Deleting or truncating reply events before the existing retention boundary.
- Adding Redis cleanup leadership, persistence, or availability requirements.
- Changing user-visible Runtime operation results.

## Requirements

### REQ-1. Historical reply isolation

A newly admitted operation must not read reply events retained for previously admitted
operations in the same connection generation.

**Acceptance criteria**

- Two Provider commands in one generation receive different reply stream identities.
- Two ordinary Runner operations in one generation receive different reply stream
  identities.
- Two Runtime Transfer dispatches in one generation receive different reply stream
  identities.

### REQ-2. Operation-local correctness

Reply ordering, bounded waits, deadlines, cancellation, and cursor resume must remain
correct within each operation.

**Acceptance criteria**

- An operation observes all of its own ordered reply events through its recorded
  cursor.
- Cancellation continues to use the original operation's recorded reply stream.
- Redis and in-memory coordination retain the same observable operation behavior.

### REQ-3. Recorded operation continuity

An admitted operation's recorded reply stream identity must remain authoritative when
delivery or observation resumes.

**Acceptance criteria**

- Existing ordinary operation metadata can continue to append and observe replies
  through its recorded stream.
- Existing Runtime Transfer metadata can resume dispatch through its recorded stream
  even when newly admitted transfers use isolated streams.

### REQ-4. Bounded retention and observability

Reply isolation must preserve bounded retention and operational evidence without
introducing destructive cleanup races.

**Acceptance criteria**

- Reply append remains the only operation that refreshes the existing stream TTL.
- Reply reads and waits remain non-mutating.
- Examined and mismatched reply counts remain bounded process-local metrics without
  request, Runtime, Session, cursor, or payload dimensions.

## Fixed Constraints

- Redis remains optional and non-authoritative.
- Operation metadata remains the authority for an admitted operation's stream
  identities.
- Blocking waits remain bounded, cancellation-safe, race-safe, and non-polling.
- Non-idempotent Runtime operations are not automatically retried.

## Open Assumptions

- Existing TTL-based cleanup remains sufficient once historical reply scanning is
  removed from newly admitted operations.

## Confirmation

On 2026-09-12 the requester instructed a code-level correction and prioritized low
complexity, maintainability, and prevention of recurrence over minimum diff size.
This document captures that implementation objective and existing correctness
constraints; a separate document-level approval was not requested or obtained.
