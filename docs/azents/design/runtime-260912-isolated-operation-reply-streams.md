---
title: "Isolated Runtime Operation Reply Streams Design"
created: 2026-09-12
updated: 2026-09-12
tags: [runtime, performance, reliability, architecture]
document_role: primary
document_type: design
snapshot_id: runtime-260912
---

# runtime-260912/DESIGN: Isolated Runtime Operation Reply Streams

## Current Behavior and Gap

Provider commands, ordinary Runner operations, and Runtime Transfer dispatches use
generation-scoped request streams. Before this snapshot they also used
generation-scoped reply streams. A new foreground waiter commonly starts with no
cursor, reads retained rows in bounded batches, filters other request identities, and
only then reaches its own replies.

Bounded blocking waits remove idle polling, but they do not prevent historical replay
while unrelated rows remain present. Runtime Transfer constructs its stream identity
outside the ordinary control-protocol dispatch path, so changing only that path leaves
a recurrence.

## Requirement and Decision Traceability

- `runtime-260912/REQ-1` is implemented by request-scoped reply allocation from
  `runtime-260912/ADR-D1` and the canonical helper from
  `runtime-260912/ADR-D4`.
- `runtime-260912/REQ-2` is implemented by retaining operation-local cursor waits,
  cancellation routing, and request-identity filtering under
  `runtime-260912/ADR-D2`.
- `runtime-260912/REQ-3` is implemented by using recorded operation metadata during
  Runtime Transfer resume under `runtime-260912/ADR-D2`.
- `runtime-260912/REQ-4` is implemented by the unchanged append-driven TTL and bounded
  metrics under `runtime-260912/ADR-D3`.

## Architecture and Ownership

`RuntimeCoordinationStore` remains the only cross-replica volatile coordination
abstraction. Generation-scoped request stream ownership, consumer groups, operation
metadata, generation fencing, and reply append/read/wait contracts remain unchanged.

New reply stream names are constructed by
`azents.runtime.coordination.stream_ids.operation_reply_stream_id`. The helper accepts
the coordination target, subject identity, canonical generation, and stable request
identity. It has no Redis dependency beyond the canonical generation representation.

`RuntimeControlProtocolService` allocates a new request identity and constructs the
corresponding reply stream before atomic operation admission. Provider and ordinary
Runner dispatch therefore share one naming path.

`RuntimeTransferCoordinator` uses the transfer dispatch request identity for new
operations. Before generating a stream, it looks up an identity-compatible existing
operation. When present, the recorded `reply_stream_id` is reused. The existing atomic
admission script remains the final compatibility and generation fence.

## Runtime Behavior

1. Control resolves the current Provider or Runner generation.
2. The dispatcher obtains a stable request identity.
3. A new operation receives a request-scoped reply stream.
4. Atomic admission records the exact request and reply stream identities and appends
   the request to the generation-scoped request stream.
5. Provider or Runner replies append only to the stream named by the admitted
   envelope and metadata.
6. Foreground observation reads and waits from its operation-local cursor.
7. Request-identity filtering remains active. It is normally a no-op for new streams
   and preserves recorded pre-cutover streams during rollout.
8. Cancellation and terminal synthesis append through the operation metadata's
   recorded stream.

Runtime Transfer resume first resolves identity-compatible operation metadata. A
recorded stream wins over a newly computed name. A missing operation receives the new
request-scoped identity. Incompatible metadata remains rejected by the existing atomic
operation contract.

## State, Retention, and Recovery

No operation metadata field, Redis schema version, request envelope field, or public
API changes. Existing stream TTL values and append-driven refresh behavior remain
unchanged. Reads and waits remain non-mutating.

No eager delete, trim, cleanup leader, or in-memory timer is introduced. An empty Redis
instance continues to fail prior in-flight work closed and permits fresh registration
and new work without restoration.

Rolling deployment does not rename recorded operations. Newly admitted operations use
isolated streams while existing metadata continues to name its original stream until
the existing operation and stream retention expire.

## Failure, Retry, and Cancellation

- Connection and generation replacement continue to fail admission through the
  existing atomic fences.
- A transfer resume with incompatible operation metadata remains rejected rather than
  creating a second reply authority.
- Request-identity filtering prevents an unrelated event in a recorded shared stream
  from completing the wrong operation and increments the existing bounded metric.
- Non-idempotent Runtime work is not automatically retried.
- Wait timeout remains a deadline and cancellation reconciliation signal, not a
  completion result.

## Observability

Existing fixed-cardinality waiter, wait-outcome, examined/filtered-row,
append-to-observation latency, and event-loop lag metrics remain. New request-scoped
streams should reduce filtered rows to zero after pre-cutover streams expire. No
request, operation, Runtime, Session, cursor, or payload dimension is added.

## Test Strategy

### Primary verification

- Dispatch concurrent ordinary Runner operations in one generation and prove distinct
  reply streams, independent cursor order, and zero filtered rows.
- Dispatch multiple Provider commands in one generation and prove distinct reply
  streams.
- Dispatch multiple Runtime Transfers in one generation and prove distinct reply
  streams.
- Resume ordinary operation observation from a recorded shared stream and prove
  request filtering.
- Resume a persisted Runtime Transfer with recorded shared-stream metadata and prove
  the request envelope keeps that stream.
- Run the Redis and in-memory coordination contract suite to preserve equivalent
  behavior.

### E2E verification

After deployment, execute sequential and overlapping Runtime tool operations on one
long-lived Runner generation. Evidence should show normal result correctness,
bounded observation latency, no growing filtered-row count for new operations, and no
Worker restart or memory regression.

No new fixture or credential is required. Required CI fails on any unit, contract,
type, lint, formatting, or existing Runtime E2E regression. Live operational
measurement is rollout evidence rather than a reason to skip deterministic CI.

## Alternatives and Non-Blocking Risks

The selected design prefers more short-lived Redis keys over shared historical
scanning. Existing TTL bounds key lifetime. If key-count pressure becomes material,
that evidence should drive a separate retention change rather than reintroducing
cross-operation reply streams.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | New Provider, Runner, and Transfer operations use request-scoped reply streams. | `runtime-260912/REQ-1`, `runtime-260912/ADR-D1` | `decided` |
| M2 | Recorded operation metadata remains the stream authority during resume and cancellation. | `runtime-260912/REQ-2`, `runtime-260912/REQ-3`, `runtime-260912/ADR-D2` | `decided` |
| M3 | Existing append-driven TTL and non-mutating observation remain unchanged. | `runtime-260912/REQ-4`, `runtime-260912/ADR-D3` | `existing` |
| M4 | One canonical helper constructs new reply stream identities. | `runtime-260912/REQ-1`, `runtime-260912/ADR-D4` | `decided` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Provider and ordinary Runner generation-scoped reply allocation | `runtime-260912/ADR-D1` | M1 and M4 | New dispatch only | Service tests assert distinct request-scoped identities. |
| Runtime Transfer generation-scoped reply allocation | `runtime-260912/ADR-D1` | M1, M2, and M4 | New transfer operations; recorded metadata remains authoritative | Transfer tests cover new isolation and existing-operation resume. |
| Independent reply stream naming helpers | `runtime-260912/ADR-D4` | M4 | Provider, Runner, and Transfer new allocation | Repository search finds one canonical new-reply helper. |
| Eager delete, trimming, or new cleanup state | None | Existing TTL behavior under M3 | Not applicable | Diff contains no delete, trim, cleanup leader, or in-memory timer. |

## Authority and Feasibility Validation

- Every requirement maps to M1-M4 and deterministic tests.
- Existing operation metadata already records exact reply stream identity and is
  sufficient for resume authority without a schema migration.
- Transfer dispatch request identity is stable across resume.
- Provider, Runner, and Transfer reply append paths already consume the stream stored
  in the admitted envelope or metadata.
- Redis and in-memory stores require no adapter-specific behavior change.
- No public API, protobuf, database migration, credential, or infrastructure change is
  required.

Result: `feasible`.

## Design Approval

This snapshot records a directly requested implementation, not a separately completed
formal design-approval workflow. On 2026-09-12 the requester prioritized a recommended
low-complexity, maintainable correction over a minimum-diff patch. Independent technical
review recommended the allocation, metadata-authority, and retention approach recorded
here, and code review found no runtime correctness findings. That review does not
constitute separate requester approval of Design revision `1` or authorization to
merge or deploy.
