---
title: "ID-Ordered Event Transcript"
created: 2026-08-31
tags: [conversation, event, engine, reliability, architecture]
document_role: primary
document_type: adr
snapshot_id: event-260831
---

# ID-Ordered Event Transcript ADR

- Snapshot: `event-260831`
- Document reference: `event-260831/ADR`
- Requirements: [event-260831/REQ](../requirements/event-260831-id-ordered-transcript.md)

## Context

The event table currently stores both a UUIDv7 event ID and a per-Session
`model_order`. Every ordinary append locks the Session row, reads the maximum logical
order, and allocates the next value. Compaction uses gaps in that order to place a
physically later summary before events that arrived during summary generation.

On 2026-08-31, Tool-result finalization held the Session lock from logical-order
allocation and then requested the Agent parent lock while External Channel ingress
held the Agent lock and requested a Session foreign-key lock. PostgreSQL selected the
Tool-result transaction as a deadlock victim after the provider effect had already
completed.

The requester confirmed that historical event insertion is no longer an authorized
product behavior and requested complete removal of the redundant order.

## Decisions

### `event-260831/ADR-D1` — Make event ID the only transcript order

**Affects:** `event-260831/REQ-1`, `event-260831/REQ-3`,
`event-260831/REQ-4`

All model-input selection, event ranges, latest-event selection, revert boundaries,
fork ordering, cleanup cursors, public projections, and frontend comparisons use the
existing event ID. The separate logical order, its allocation lock, persistence,
indexes, API field, and generated-client field are removed.

Rejected alternatives:

- Retaining `model_order` only internally preserves the append lock and two competing
  ordering authorities.
- Replacing it with another sequence column renames the same redundant source of
  truth.
- Keeping a public compatibility field retains an unsupported contract and requires
  fabricated values after persistence removal.

### `event-260831/ADR-D2` — Reject compaction when its transcript tail changes

**Affects:** `event-260831/REQ-2`, `event-260831/REQ-4`

Compaction captures both the current model-input head and selected tail. External
summary generation remains outside database transactions. The final transaction
locks and revalidates both boundaries before appending the marker and summary. A
changed head or tail makes the plan stale and produces no durable compaction event.

Rejected alternatives:

- Holding the Session lock through provider latency blocks input and recreates a
  long-lived contention boundary.
- Appending the summary after a changed tail and moving the head would hide the
  concurrent events under pure ID filtering.
- Replaying or copying concurrent events after the summary duplicates durable
  transcript state.

### `event-260831/ADR-D3` — Remove legacy ordering without fallback

**Affects:** `event-260831/REQ-3`

The migration removes the obsolete columns and indexes directly. Current model-input
heads are validated against ID order before removal. Historical migration and design
records remain unchanged, but runtime code and current Living Specs contain no
logical-order compatibility path.

Rejected alternatives:

- Dual-read or dual-write operation would preserve the obsolete authority and its
  failure modes.
- A nullable deprecated field would leave generated clients and downstream code
  dependent on state that no longer has meaning.

### `event-260831/ADR-D4` — Treat schema contraction as a maintenance migration

**Affects:** `event-260831/REQ-3`

The deployment applying this one-time contract migration stops old application
processes that read or write the removed columns before upgrading the schema, then
starts only the new version. The migration itself blocks concurrent legacy writes
from compatibility preflight through schema removal. It does not add mixed-version
compatibility columns or a permanent rollout coordinator.

Rejected alternatives:

- A dual-read or dual-write rollout would preserve the obsolete ordering authority.
- A new generalized deployment-quiescence controller is broader than this one-time
  breaking migration.
- Allowing ordinary rolling startup to apply the contraction would leave old
  processes running against a schema they cannot use.

## Consequences

- Ordinary event append no longer takes a Session `FOR UPDATE` lock to allocate
  ordering state.
- Compaction can discard completed summary work when concurrent durable events change
  its selected tail.
- ModelFile GC uses event-ID head and cursor fields already present on AgentSession.
- The public OpenAPI contract changes and generated clients must be regenerated.
- Applying the contract migration requires a maintenance window that quiesces old
  event-writing processes before schema upgrade.
- The existing UUIDv7 event ID becomes the sole ordering contract; a future
  cluster-global allocator would require a separate product decision.
