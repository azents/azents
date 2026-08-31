---
title: "ID-Ordered Event Transcript Design"
created: 2026-08-31
updated: 2026-08-31
tags: [conversation, event, engine, reliability, backend, frontend]
document_role: primary
document_type: design
snapshot_id: event-260831
---

# ID-Ordered Event Transcript Design

- Snapshot: `event-260831`
- Document reference: `event-260831/DESIGN`
- Requirements: [event-260831/REQ](../requirements/event-260831-id-ordered-transcript.md)
- ADR: [event-260831/ADR](../adr/event-260831-id-ordered-transcript.md)

## Current Behavior and Requirement Gaps

`events.model_order` is allocated by locking the Session row and reading the maximum
value. Model input, fork context, retry selection, revert ranges, and ModelFile GC use
the logical order while UI history already uses event-ID pagination.

Compaction captures the current model-input transcript, generates a summary without an
open transaction, then assigns marker and summary orders immediately after the
selected tail. This preserves concurrent events by logically inserting the summary
before them, but the requester has removed historical insertion from product scope.

The order allocation lock also creates a Session-to-Agent lock path before Session
activity projection. External Channel ingress uses Agent-to-Session order, producing
the observed deadlock.

## Requirement and ADR Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `event-260831/REQ-1` | ID-only repository ordering, filtering, cursor, and domain contracts. |
| `event-260831/REQ-2` | Head-and-tail compaction plan validation and physical-tail append. |
| `event-260831/REQ-3` | Persistence migration, API removal, client regeneration, and frontend replacement. |
| `event-260831/REQ-4` | ID-range revert, fork, retry, and ModelFile GC behavior. |

## Architecture and Ownership

`events.id` is the single durable transcript order and cursor. Event payloads remain
the transcript source of truth. `agent_sessions.model_input_head_event_id` remains the
model-input boundary, and `model_file_gc_cursor_event_id` remains cleanup progress.

The event repository owns ID comparisons and event-range queries. The Session
repository owns head movement and cleanup cursor advancement. The compactor owns
optimistic plan validation. API and frontend layers consume event IDs without
deriving another order.

## Event Append and Read Behavior

Event creation no longer accepts or allocates a logical order. Appends generate the
existing UUIDv7 ID and insert the event. The event foreign key may take a Session
key-share reference, but no Session `FOR UPDATE` lock is used for ordering.

Model-input reads select non-reverted events in ascending ID order. With no head they
return the complete Session transcript. With a head they resolve that event in the
same Session and return events whose IDs are greater than or equal to the head ID.

Recent event reads, retry-visible selection, edit/retry reversion, and fork context
use the same ID ordering. Parent events copied to a child Session receive new child
event IDs in the already selected order.

## Compaction Lifecycle

The selected transcript supplies:

- `expected_head_event_id`, read from AgentSession before summary generation; and
- `expected_tail_event_id`, the final event in the selected ID-ordered transcript.

Summary generation, continuity rendering, and hooks remain outside database
transactions. During the final transaction, the compactor locks the Session and
validates:

1. the current model-input head still equals `expected_head_event_id`; and
2. the latest non-reverted Session event ID still equals `expected_tail_event_id`.

Any mismatch raises `CompactionPlanStaleError`. The transaction appends no marker or
summary, does not reset Tool Search working state, and does not move the head.

When both boundaries match, marker and summary append consecutively at the physical
tail. The summary payload retains `covered_until_event_id`. The Session head moves to
the summary ID in the same transaction. Future input therefore consists of the
summary and later ID-ordered events.

## Edit, Retry, and Fork Behavior

Message edit and failed-run retry mark non-reverted events with
`id >= target_event_id` as reverted. The model-input-head eligibility check compares
the target ID with the current head ID.

Latest retry eligibility scans descending event IDs. Fork selection sorts parent
events by ID, applies the existing head boundary, selects the requested turns, and
appends them to the child in that order.

## ModelFile Cleanup

AgentSession drops numeric head and cursor order columns. The scheduler selects a
Session when `model_input_head_event_id` is non-null and differs from
`model_file_gc_cursor_event_id`.

Cleanup scans non-reverted events where:

```text
event.id > cursor_event_id, when a cursor exists
event.id <= model_input_head_event_id
```

The existing `(session_id, id)` event index serves the range. After each bounded
batch, the cursor advances monotonically to the last processed event ID, or exactly
to the head when the range is exhausted. Concurrent cleanup attempts use a
conditional cursor comparison so an older attempt cannot move progress backward.

## Persistence Migration

A generated Alembic migration:

1. verifies that every current model-input head has no non-reverted event whose
   physical ID precedes the head while its logical order follows the head;
2. drops `ix_events_session_model_order`;
3. drops `events.model_order`;
4. drops `ix_agent_sessions_model_file_gc_lag`;
5. drops `agent_sessions.model_input_head_model_order`; and
6. drops `agent_sessions.model_file_gc_cursor_model_order`.

Existing event IDs, model-input head IDs, cleanup cursor IDs, and historical rows are
preserved. Downgrade may reconstruct logical orders from ascending event IDs because
the removed historical-insertion behavior is not restored.

## API and Frontend

`ChatEventResponse` removes `model_order`. OpenAPI is regenerated, followed by Python
and TypeScript public clients.

The Web client selects the latest durable requested inference profile by event ID
within fetched durable events. Existing history pagination remains unchanged because
it already uses event-ID cursors.

## Failure, Retry, and Recovery

Compaction tail changes are ordinary stale-plan failures and write no partial state.
The owning run retry boundary rebuilds input from current durable history. No retry
path recreates logical insertion.

Migration validation fails closed if an active head cannot be represented by pure ID
filtering. Runtime does not keep a fallback order column or hidden compatibility
branch.

## Observability and Operational Risks

Existing compaction failure telemetry identifies stale attempts. Focused logging and
tests distinguish head changes from tail changes without exposing transcript
payloads.

The existing UUIDv7 generator is process-local monotonic rather than a
cluster-global sequence. Production evidence showed no non-compaction divergence
between ID and logical order, and UI pagination already treats ID as canonical. A
future stricter allocation guarantee is outside this snapshot.

## Test Strategy

The primary verification matrix covers:

- repository append without Session order allocation or lock;
- model-input, revert, retry, fork, and cleanup ID ranges;
- compaction success with unchanged boundaries;
- compaction rejection when either head or tail changes;
- migration upgrade and downgrade schema assertions;
- public OpenAPI and generated-client absence of `model_order`;
- Web latest-inference selection under ID-ordered events; and
- existing chat and compaction E2E flows.

Focused backend repository, engine, service, migration, Ruff, and configured type
checks run before the full backend suite. Public clients are regenerated from
OpenAPI, then frontend tests, formatting, lint, type checking, and build run. Existing
E2E fixtures are sufficient; no live provider credentials or new fixture data are
required. Required CI is the authoritative integration evidence, and skipped required
checks are failures rather than accepted evidence.

## Alternatives and Non-Blocking Risks

- A database-global sequence would provide a stronger allocation order but would
  replace rather than remove the second ordering authority.
- Serializing all event writes through one Session actor could strengthen UUIDv7
  ordering but is broader than the deadlock and obsolete-state removal requested
  here.
- Highly concurrent durable event writers can make compaction stale repeatedly. The
  existing bounded run retry and backoff behavior prevents an unbounded tight loop.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Event ID is the only transcript order and range cursor | `event-260831/REQ-1`, `event-260831/REQ-3`, `event-260831/ADR-D1` | `decided` |
| M2 | Compaction validates both selected head and tail before physical-tail append | `event-260831/REQ-2`, `event-260831/ADR-D2` | `decided` |
| M3 | Edit, retry, fork, and ModelFile GC use ID boundaries | `event-260831/REQ-4`, `event-260831/ADR-D1` | `decided` |
| M4 | Logical-order persistence and public contracts are removed without fallback | `event-260831/REQ-3`, `event-260831/ADR-D3` | `decided` |
| M5 | External model latency remains outside compaction transactions | `event-260831/REQ-2`, current Context Compaction Spec | `existing` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Per-Session model-order allocation and Session lock | M1, M4 | UUIDv7 event ID append order | Event repository and tests | Repository search and lock-concurrency test |
| Logical compaction insertion before concurrent events | M2, M4 | Head-and-tail stale validation | Compactor and tests | Concurrent-tail stale test and search |
| Event and AgentSession logical-order columns and indexes | M4 | Existing head/cursor event IDs and `(session_id, id)` index | RDB models and migration | Migration tests and schema inspection |
| Model-order revert, retry, fork, and cleanup ranges | M3 | Event-ID ranges | Repositories, services, engine | Focused behavior tests |
| Public and generated `model_order` field | M4 | Event ID or existing page order | OpenAPI, generated clients, Web | Generated-code and repository search |
| Current Living Spec logical-order text | M1, M2, M3, M4 | ID-only current behavior | Conversation, compaction, periodic execution Specs | Spec review and documentation search |
| Historical implemented documents and executed migrations | Project immutability constraint | None | No edits | Git diff confirms unchanged files |

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-08-31`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5`
- Approved scope: remove `model_order` and every dependent persisted/public contract,
  make event ID the sole transcript order, and replace compaction logical insertion
  with head-and-tail stale validation.
