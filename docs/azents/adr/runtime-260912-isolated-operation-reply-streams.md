---
title: "Isolated Runtime Operation Reply Streams"
created: 2026-09-12
tags: [runtime, performance, reliability, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260912
---

# runtime-260912/ADR: Isolated Runtime Operation Reply Streams

This ADR records the replacement decisions for the confirmed
[Isolated Runtime Operation Reply Streams Requirements](../requirements/runtime-260912-isolated-operation-reply-streams.md)
(`runtime-260912/REQ`).

## Context

`runtime-260910/ADR-D1` introduced bounded blocking reply waits while retaining one
shared reply stream per connection generation. Each waiter therefore begins at its
cursor and filters events for other requests. Production investigation found that a
new waiter commonly starts without a cursor and can traverse retained completed
operation history before reaching its own reply.

The same shared-stream pattern exists in Provider command dispatch, ordinary Runner
operation dispatch, and Runtime Transfer dispatch. Transfer dispatch can also resume
from persisted operation metadata, so a rollout must continue to honor the stream
identity already recorded for an admitted transfer.

## Decisions

### runtime-260912/ADR-D1. Allocate one reply stream per newly admitted request

New Provider commands, ordinary Runner operations, and Runtime Transfer dispatches
receive deterministic request-scoped reply streams. Generation-scoped request streams
and consumer groups remain unchanged.

The canonical reply stream identity includes target, subject, canonical connection
generation, and stable request identity. Runtime Transfer uses its stable dispatch
request identity, so a retry computes the same stream.

This replaces the shared-stream allocation decision for new operations in
`runtime-260910/ADR-D1` and satisfies `runtime-260912/REQ-1`.

**Rejected alternatives**

- Capturing a generation-stream tail cursor at dispatch, because it adds another
  coordination contract and persisted cursor while continuing cross-operation wakeups
  and filtering.
- Trimming a shared stream to a fixed length, because an active operation can lose
  required events.
- Optimizing only ordinary Runner operations, because Provider commands and Runtime
  Transfers would retain the same recurrence path.

### runtime-260912/ADR-D2. Treat recorded operation metadata as resume authority

When an operation already exists, its recorded `reply_stream_id` remains authoritative.
Runtime Transfer resume uses an identity-compatible existing operation record before
constructing a stream for a new dispatch. Atomic operation admission remains the final
fence against incompatible metadata.

Ordinary cancellation and terminal reply paths already use the operation record and
continue unchanged. Request-identity filtering remains in the reply observer so a
recorded pre-cutover shared stream remains safe during rolling deployment and
mismatched events remain observable.

This satisfies `runtime-260912/REQ-2` and `runtime-260912/REQ-3`.

**Rejected alternatives**

- Recomputing the stream name during every transfer resume, because it rejects or
  misroutes operations admitted before the rollout.
- Branching on a legacy stream-name pattern, because persisted operation identity is
  the actual authority.
- Removing request-identity filtering immediately, because it would break observation
  of already recorded shared streams.

### runtime-260912/ADR-D3. Preserve append-driven TTL retention without eager deletion

Reply append continues to refresh the existing bounded stream TTL. Reads and waits
remain non-mutating. Final observation does not delete or trim the stream, and the
in-memory implementation does not add timer-based garbage collection.

This satisfies `runtime-260912/REQ-4`.

**Rejected alternatives**

- Deleting a stream immediately after one waiter sees a final event, because another
  authorized resume can still require the recorded cursor history.
- Shortening retention only for isolated streams, because that creates two lifecycle
  contracts during rollout.
- Adding a Redis cleanup leader, because Redis must remain optional and
  non-authoritative.

### runtime-260912/ADR-D4. Centralize canonical reply stream identity construction

Provider, Runner, and Runtime Transfer dispatch use one coordination helper for new
reply stream identities. Tests cover canonical signed-generation formatting and
request scoping.

This reduces naming drift and supports `runtime-260912/REQ-1`.

## Consequences

- New operation observation no longer traverses replies retained for completed
  operations in the same generation.
- Concurrent operations use independent cursors and Redis blocking reads.
- Generation-scoped request ordering and cancellation ordering remain unchanged.
- Existing admitted operations continue through their recorded stream identity.
- Retained pre-cutover shared streams can still produce filtered-row metrics until
  their existing TTL expires.
- Redis may temporarily hold more stream keys, but each key contains only one
  operation's events and expires under the existing bounded retention policy.

## Risks and Mitigations

- **Key-count increase:** request-scoped streams create more keys. Existing bounded TTL
  limits lifetime, and no active operation scans unrelated keys.
- **Partial rollout:** existing operation metadata may name a shared stream. Metadata
  authority and retained request filtering preserve resume behavior.
- **Naming drift:** one canonical helper and Provider/Runner/Transfer tests prevent
  independent stream formats.
- **Transfer recurrence:** dedicated concurrent-transfer and resume tests cover the
  previously separate dispatch implementation.
