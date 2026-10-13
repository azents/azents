---
title: "Compacted Event Retention Design"
created: 2026-10-13
tags: [retention, conversation, backend]
document_role: primary
document_type: design
snapshot_id: retention-261013
---

# Compacted Event Retention Design

Authority: [Requirements](../requirements/retention-261013-compacted-events.md) and [ADR](../adr/retention-261013-compacted-events.md).

## Current Behavior and Scope

Compaction appends a marker/summary pair and atomically advances the Session model-input head. Original events remain in the transcript. Archive retention has an administrator-owned singleton and a five-minute periodic purge task. ModelFile GC reads event payloads and advances a per-Session event cursor.

## Mechanisms

Add nullable `events.compacted_at` to record first displacement. The two production Session head repository implementations invoke the same repository helper in their existing head transaction. The helper recognizes compaction summaries, records the summary creation timestamp only on earlier events without a timestamp, and leaves timestamps unchanged during later compaction. No timestamp is recorded for a stale/failed compaction.

Add nullable `compacted_event_retention_days` to existing lifecycle settings; null means Unlimited and is the installation/upgrade default. Add a separate administrator mutation with the existing revision CAS, leaving archive policy and recalculation unchanged. Current finite policy applies at each cleanup pass to all eligible events. Moving to Unlimited prevents future passes; already deleted events cannot be recovered.

The independent five-minute cleanup task processes bounded event batches. It locks settings while determining and deleting a batch, protecting against a concurrent switch to Unlimited. Eligibility requires elapsed TTL, ID strictly before the current head, and an ID at or behind the ModelFile GC cursor. Pending/running Run input references are excluded. Row locking with skip-locked keeps retries and concurrent passes idempotent. Each pass reports deletion count and whether its batch limit was reached.

## Migration and Recovery

Alembic adds the nullable columns and a partial expiration index. For existing events, reconstruct displacement from ordered retained compaction summaries: each summary timestamps the interval from the previous summary (inclusive) to itself (exclusive), bounded by the current Session head. This uses durable summary timestamps rather than event creation age. Unprovable displacement remains null and is preserved.

The default remains Unlimited throughout migration. No blobs or entire Sessions are removed by this task. Existing ModelFile cleanup owns file deletion; event cleanup waits for its cursor. Failure rolls back the batch and the existing scheduler retries. Downgrade removes the new state and task code stops with deployment rollback.

## Administrator UI

Extend the existing retention screen with a separate compacted-event section using existing Unlimited/whole-days controls, independent saving state, visible permanent-deletion explanation, and standard conflict/error recovery. Preserve archive controls and progress. Regenerate OpenAPI clients through existing generation tools.

## Design Authority

- Design revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Separate Unlimited-default administrator policy | REQ-1 | required |
| M2 | Durable first-displacement timestamp without resetting age | REQ-2, ADR-D1 | derived |
| M3 | Bounded periodic deletion strictly behind current head | REQ-2, REQ-3; existing scheduler | derived |
| M4 | Preserve file-GC evidence and active input references | REQ-3; existing file lifecycle and Run ownership | derived |
| M5 | Backfill only displacement supported by existing summaries | ADR-D1; existing transcript authority | derived |

## Removal and Replacement

Pre-head events past configured TTL are permanently removed under REQ-2. Current transcript readers naturally return the retained history. Replace unconditional indefinite-history claims in Living Specs with the new optional retention policy. Regenerate affected client schemas. Archive lifecycle, model context, file lifecycle and Session identity remain unchanged. Verify current head preservation, default-disabled behavior and removal boundaries in integration tests.

## Test Strategy

Primary product flow: administrator reads Unlimited, saves finite compacted-event retention independently, compacts a conversation, and scheduler cleanup removes only expired obsolete history. A 60-day elapsed-time flow is verified deterministically in backend PostgreSQL tests rather than with live wall-clock waits or direct testenv writes.

Cover timestamp capture under successful compaction, repeated compaction, rollback/stale attempts, missing head, Unlimited/zero TTL, exact TTL boundary, file GC lag, pending/running inputs, bounded repeatable deletion, revision conflicts and invalid values. Test schema upgrade/downgrade and historical backfill. Existing Docker PostgreSQL fixture applies migrations; no provider credentials are needed. Run focused backend tests, lint/type checks, generated-client validation, Admin Web typecheck/build and CI. Record commands and skipped/unavailable coverage explicitly. Live provider/UI validation requires a prepared development environment and is not inferred from static checks.

## Feasibility

Repository evidence supports all mechanisms: monotonic ID ordering, immutable summary timestamps, nullable schema extension, existing lifecycle settings CAS, per-Session GC cursor, Run input association and scheduler retry registration. Performance risk is event timestamp updates during compaction; update only unmarked events and index eligible timestamps. Unlimited still records displacement so later finite policies have accurate evidence.

## Design Approval

- Mode: Collaborative.
- Decision owner: requester.
- Date: 2026-10-13.
- Implementation scope authorized after the requester confirmed REQ and ADR-D1.
- Authorized scope: M1–M5; first-displacement retention, Unlimited default, current-context preservation and existing scheduled maintenance approach.
- Local implementation details: nullable event timestamp, repository helper, endpoint names, batch/index layout and fixture composition.
