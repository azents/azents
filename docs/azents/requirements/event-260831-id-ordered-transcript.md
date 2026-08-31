---
title: "ID-Ordered Event Transcript Requirements"
created: 2026-08-31
updated: 2026-08-31
tags: [conversation, event, engine, reliability]
document_role: primary
document_type: requirements
snapshot_id: event-260831
---

# ID-Ordered Event Transcript Requirements

- Snapshot: `event-260831`
- Document reference: `event-260831/REQ`

## Problem

The event transcript maintains a second logical ordering value in addition to its
durable event identity. Allocating that value locks the Session for every append and
can deadlock with concurrent conversation ingress after a Tool effect has already
completed, leaving the Tool result unrecorded and causing the Agent to repeat the
effect.

The logical ordering was introduced to insert events into earlier model history, but
that behavior is no longer part of the product contract.

## Primary Actor

A participant using an Agent Session while durable events may arrive from concurrent
runtime or external-channel activity.

## Primary Scenario

The Agent completes a Tool call while another process admits conversation activity.
The Tool result is durably appended once, the Session remains usable, and future UI
and model history follow the same event-ID order without a Session-wide ordering
allocation lock.

## Supporting Scenarios

- Context compaction completes only when its selected transcript remains current.
- Message edit and failed-run retry hide the target event and every later event.
- Forked Agent context preserves the selected parent event order.
- ModelFile cleanup advances from the previous event cursor through the current
  model-input head.

## Goals

- Use one durable ordering source for UI history, model input, and event-range
  operations.
- Remove the Session lock used only to allocate a second event order.
- Prevent compaction from losing events appended during summary generation.
- Remove obsolete persisted, API, generated-client, and frontend ordering state.

## Non-Goals

- Supporting insertion of new events into an earlier history position.
- Changing event payload semantics, Session ownership, or history pagination shape
  beyond removal of the redundant order field.
- Holding a database transaction or Session row lock during external summary model
  latency.
- Adding a replacement sequence column or compatibility fallback.

## Requirements

### REQ-1. One canonical transcript order

Durable event identity must be the only ordering and cursor source for Session event
history.

**Acceptance criteria**

- UI history and future model input use ascending event-ID order.
- Event head, range, latest-event, and revert comparisons use event IDs.
- Event append does not allocate or update a separate per-Session order.

### REQ-2. Safe compaction without historical insertion

Compaction must not insert its marker or summary before an event that already exists.

**Acceptance criteria**

- A compaction plan records the selected model-input head and tail event IDs.
- If either boundary changes before commit, the attempt writes no marker or summary,
  does not move the model-input head, and is classified as stale.
- A successful marker and summary append at the durable tail, and future model input
  starts at the summary event.

### REQ-3. Remove redundant order state and contracts

The obsolete logical order must not remain as persisted state or a public contract.

**Acceptance criteria**

- Event and AgentSession logical-order columns and indexes are removed.
- Public event responses and generated clients no longer expose the logical order.
- Frontend behavior uses event identity or existing page order instead.

### REQ-4. Preserve ID-range behavior

Existing event-range workflows must retain their observable behavior under event-ID
ordering.

**Acceptance criteria**

- Edit and failed-run retry revert the selected event and every later event.
- Fork selection retains the current model-input head boundary and chronological
  order.
- ModelFile cleanup scans and advances bounded event-ID cursor ranges without
  deleting files still reachable from current model input.

## Fixed Constraints

- Inserting events into earlier history is removed product behavior.
- Durable event IDs remain the existing fixed-width UUIDv7 hexadecimal identifiers.
- Historical implemented Requirements, ADRs, Designs, and executed migrations remain
  unchanged.
- No backward-compatibility field or legacy ordering fallback is required.

## Open Assumptions

- Existing event-ID ordering, already used by history pagination, remains the accepted
  durable Session ordering contract.

## Confirmation

Confirmed by the requester on 2026-08-31 before the ADR and Design were created.
