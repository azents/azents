---
title: "Suppressed Failure Observation and Recovery"
created: 2026-08-18
tags: [architecture, backend, runtime, cleanup, observability, avatar]
document_role: primary
document_type: adr
snapshot_id: cleanup-260818
---

# cleanup-260818/ADR: Suppressed Failure Observation and Recovery

## Context

The confirmed
[cleanup-260818/REQ](../requirements/cleanup-260818-suppressed-failure-recovery.md)
requires exactly-once observation for suppressed detached exceptions, bounded
diagnostics for Runtime Transfer cleanup retries, and durable retry ownership for
superseded avatar blobs.

The three areas have different sources of truth:

- model-stream and Local Job Runtime cleanup helpers are the final in-process
  observers of tasks whose primary timeout or cancellation result is already
  fixed;
- Runtime Transfer cleanup authority is its bounded Memory or Redis attempt
  record and existing repair loops; and
- Agent avatar metadata is durable PostgreSQL product state, while public S3
  deletion happens after the database mutation.

The requester fixed the required outcomes and compatibility constraints. The
remaining choices are derived architecture decisions needed to satisfy them.

## Decisions

### cleanup-260818/ADR-D1 — Log at the final suppressing observer

Each identified detached-task boundary records a warning with stack-trace
evidence only when it consumes an unexpected exception and no upstream observer
will receive it. Expected cancellation remains silent. The boundary continues to
suppress the exception so the already determined timeout or cancellation result
does not change.

This applies to cleanup-260818/REQ-1.

Logging at the original primary-operation boundary is rejected because the late
exception does not determine that result and may not exist yet. Logging both
there and in the cleanup helper is rejected because it would duplicate exception
aggregation. Re-raising from the final observer is rejected because no caller is
responsible for changing the committed primary result.

The same final-observer rule applies when Runtime-to-Server transfer cleanup
exhausts its bounded abandon, status-recovery, and cancellation-confirmation
paths. An authoritative terminal status ends cleanup silently; otherwise the
last suppressed cleanup exception is recorded once without changing the
transfer result.

### cleanup-260818/ADR-D2 — Keep transfer cleanup diagnostics in existing volatile state

Runtime Transfer extends its existing attempt record with bounded cleanup-failure
evidence. The evidence identifies the stable cleanup artifact or operation,
records the latest observation time and bounded attempt count, and contains no
raw provider message or storage authority. A successful cleanup clears the
evidence.

Memory and Redis stores implement the same state contract. Redis advances its
strict record schema in the coordinated Runtime Control deployment. The
diagnostic is internal state and is not added to PostgreSQL, public APIs, or the
Runner data protocol. Existing state-backed repair and state-independent orphan
repair remain the retry authorities.

This applies to cleanup-260818/REQ-2 and REQ-4.

PostgreSQL persistence is rejected because transfer artifacts are not product
entities and Redis must remain optional. Log-only diagnostics are rejected
because they do not retain actionable evidence with the retry responsibility.
Raw exception text, storage object keys, raw provider upload IDs, endpoints,
hashes, credentials, and bytes are rejected from the new diagnostic evidence
because they are unbounded or sensitive. Existing opaque cleanup handles remain
the retry authority. Extending public or Runner protocols is rejected because no
consumer needs the diagnostic to perform cleanup.

### cleanup-260818/ADR-D3 — Use a relational avatar cleanup outbox

Avatar replacement and removal serialize the Agent row and atomically enqueue an
immutable snapshot of the superseded avatar in durable PostgreSQL state. The
cleanup row is independent of the Agent lifetime so Agent deletion cannot remove
the retry pointer.

The existing file lifecycle scheduler claims a bounded page of pending avatar
cleanup rows, deletes their deduplicated public blobs, and removes the owned row
after success. It retains bounded failure and retry evidence when deletion fails.
Cleanup remains asynchronous and does not reverse an already committed avatar
replacement or removal.

This applies to cleanup-260818/REQ-3 and REQ-4.

Continuing best-effort deletion from `AgentService` is rejected because a process
restart loses retry responsibility. Storing pending cleanup inside the Agent
avatar JSON is rejected because Agent deletion would remove it and concurrent
history could grow without a claimable lifecycle. Redis is rejected because it
is optional and ephemeral. Reusing unrelated file-resource rows is rejected
because avatar blobs do not satisfy those resources' ownership and terminal
state contracts.

### cleanup-260818/ADR-D4 — Limit avatar recovery to committed supersession

This snapshot closes the cleanup gap created when a committed replacement or
removal makes the previous avatar obsolete. It does not introduce a
prepared/adopted publication protocol for blobs created before the Agent database
mutation commits.

This applies to the non-goals and fixed scope of cleanup-260818/REQ.

Expanding the outbox to pre-adoption publication is rejected for this correction
because it requires a separate publication state machine and partial-thumbnail
compensation contract. Treating that larger lifecycle as implied by
replacement/removal retry would obscure its distinct failure and recovery
semantics.

## Consequences

- Suppressed detached failures gain stack traces without changing primary
  outcomes.
- Transfer cleanup records grow by a small bounded diagnostic object and the
  Redis record schema advances.
- A coordinated Runtime Control rollout is required for the strict Redis record
  schema; no compatibility adapter is retained.
- Avatar replacement and removal perform one additional relational write in the
  same transaction.
- File lifecycle cleanup gains bounded avatar work and counters.
- Old avatar blobs may remain physically present until a later scheduler pass
  during an S3 outage, but durable cleanup responsibility remains.
- Pre-adoption avatar publication orphan windows remain explicit future work.

## Risks

- A prolonged object-store outage can grow pending avatar cleanup rows. Bounded
  scheduler pages and indexed due-state selection prevent one pass from becoming
  unbounded.
- Concurrent avatar mutations require row-level serialization to ensure the
  superseded snapshot matches the actual previous value at commit time.
- Bounded transfer evidence describes the cleanup category rather than the
  provider's full error message; stack-trace logs remain the diagnostic source
  for the individual failed attempt.
- Redis records written by the new schema are not readable by an old Runtime
  Control binary, consistent with the existing coordinated-cutover contract.
