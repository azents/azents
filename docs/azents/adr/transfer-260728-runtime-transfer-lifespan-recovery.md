---
title: "Runtime Transfer Lifespan Recovery"
created: 2026-07-28
tags: [architecture, runtime, transfer, storage, redis, cleanup]
document_role: primary
document_type: adr
snapshot_id: transfer-260728
---

# transfer-260728/ADR: Runtime Transfer Lifespan Recovery

## Context

The confirmed
[transfer-260728/REQ](../requirements/transfer-260728-runtime-transfer-lifespan-recovery.md)
corrects deployment and recovery gaps discovered after the implemented
[transfer-260725 snapshot](../requirements/transfer-260725-runtime-file-transfer.md).
The historical snapshot already established one-hour logical expiration,
immediate exact cleanup, fail-closed state loss, a bounded transfer-prefix orphan
scan, and storage lifecycle as a coarse final defense.

The runtime enforces logical expiration and state-backed cleanup, but the
implemented repair loop only visits records still present in the selected state
store. Losing in-memory or Redis state therefore loses the cleanup handles for
orphan objects and multipart uploads.

The chart also added a `lifecycleAcknowledgement` object containing operator
names, timestamps, and hour values. Runtime Control never reads these values.
Nevertheless, the chart blocked every external-storage deployment when they
were absent. This declaration-only gate prevented the Runtime Control manifest
with the transfer-specific S3 configuration from rendering and therefore
prevented `present_file` from operating.

S3-compatible lifecycle expiration is day-granular in the common API and is
executed asynchronously by the backend. It cannot provide the synchronous
one-hour authorization boundary and must not be represented as if it does.

## Decision Backlog

The requester already fixed the hard constraints. This correction records the
following dependent decisions without reopening them:

1. runtime-versus-infrastructure lifespan authority;
2. orphan discovery after complete volatile-state loss;
3. bounded cleanup scheduling and multi-replica behavior;
4. chart and deployment-configuration contract; and
5. coordinated rollout and rollback.

No requester decision remains pending.

## Decisions

### transfer-260728/ADR-D1 — Keep one-hour authority in Runtime Control

Runtime Control remains the sole authority for the non-extendable one-hour
logical lifetime. State-store transitions and trusted consumers validate that
deadline synchronously. Settlement immediately invokes exact object deletion or
multipart abort, and state-backed repair retries known failures while records
remain available.

Storage lifecycle never authorizes a transfer, extends a deadline, determines a
terminal outcome, or turns physical deletion into a prerequisite for an already
committed feature result.

This decision applies to transfer-260728/REQ-2 and REQ-4.

Making backend lifecycle the one-hour authority is rejected because portable S3
lifecycle configuration is coarser and asynchronous. Making physical delete part
of feature success is rejected because a cleanup outage must not reverse a
committed Runtime destination or publication.

### transfer-260728/ADR-D2 — Add a Control-owned, state-independent orphan sweeper

Runtime Control extends its bounded repair loop with a transfer-prefix orphan
sweeper. The sweeper lists completed objects and incomplete multipart uploads
directly from the configured workspace bucket. It uses storage-reported
`LastModified` and multipart `Initiated` timestamps, compares them with the fixed
one-hour maximum, and deletes or aborts only artifacts at or before the cutoff.

The sweeper never asks the transfer state store whether an old artifact is
successful and never recreates state from an object. At one hour an active
attempt is already logically invalid, so deleting an artifact at that age cannot
violate a valid transfer lease.

This decision applies to transfer-260728/REQ-2 and REQ-3.

Depending only on Redis cleanup records is rejected because Redis is optional and
ephemeral. Encoding durable cleanup records in PostgreSQL is rejected because
transfer artifacts are not product entities. Relying only on storage lifecycle
is rejected because its timing is backend-dependent and too coarse.

### transfer-260728/ADR-D3 — Keep orphan scanning bounded and idempotent

Each repair interval scans at most one configured page of completed objects and
one configured page of multipart uploads. The cleanup collaborator holds only
process-local listing cursors. Reaching the end resets a cursor so later passes
rescan the prefix and retry artifacts skipped or failed during a prior cycle.

Object delete and multipart abort are exact and idempotent. Multiple Runtime
Control replicas may observe the same artifact. They do not require Redis
leadership or distributed locks because duplicate cleanup converges to the same
absent state. Per-artifact failures remain visible through structured repair
logging and are retried on a later prefix cycle.

This decision applies to transfer-260728/REQ-3.

An unbounded full-prefix sweep is rejected because it can starve Runtime Control.
A Redis-owned cursor or cleanup lock is rejected because losing Redis must not
disable recovery. Assigning cleanup to one elected replica is rejected because
the election itself would add unnecessary shared-state availability dependence.

### transfer-260728/ADR-D4 — Remove lifecycle acknowledgement from the chart contract

The Azents chart removes `server.runtimeControl.transfer.lifecycleAcknowledgement`
from values, schema, templates, tests, and operator notes. External storage
rendering validates the functional Runtime Control S3 endpoint, bucket,
credential references, transfer endpoint, backend, limits, and replica rules.
It does not validate names, timestamps, or durations that Runtime Control cannot
enforce.

Storage owners remain responsible for a backend-native transfer-prefix lifecycle
policy where supported. That policy uses the shortest supported interval for
completed objects and incomplete multipart uploads, but its configuration and
evidence are not Runtime Transfer application values.

This decision applies to transfer-260728/REQ-1 and REQ-4.

Keeping optional deprecated acknowledgement fields is rejected because they have
no runtime meaning and could regain false authority. A separate RustFS lifecycle
Job with an invented duration is rejected because it duplicates infrastructure
ownership and still cannot enforce one hour.

### transfer-260728/ADR-D5 — Use a coordinated configuration cutover

The chart schema removal and every deployment overlay that supplied the removed
value change together before chart rollout. The rejected Home lifecycle Job and
its matching acknowledgement are removed rather than migrated.

Rollback uses the previous chart and its matching previous overlay as one unit.
No transfer object is revived during rollback; logical authority remains in the
running Runtime Control version, and orphan artifacts remain eligible for exact
cleanup, the state-independent sweeper, or backend lifecycle.

This decision applies to transfer-260728/REQ-1 through REQ-4.

Allowing a new strict schema to render against an old overlay is rejected because
Helm will fail before deployment. Retaining the old value only for rollback
compatibility is rejected because the current single deployment can use the same
coordinated-cutover policy as the original Runtime Transfer rollout.

## Consequences

- `present_file` can start with real Runtime Control S3 configuration and no
  invented lifecycle acknowledgement.
- Empty memory or Redis recovery fails prior attempts closed while new transfers
  resume and old storage artifacts remain cleanup-eligible.
- Runtime Control performs additional bounded S3 list calls and may issue
  duplicate idempotent cleanup calls across replicas.
- Backend lifecycle remains useful but no longer masquerades as application
  enforcement or deployment approval.
- Exact physical deletion can lag the one-hour logical boundary by the repair
  interval, object-store availability, retry cycles, or backend lifecycle timing.
  No transfer access is permitted during that lag.

## Risks

- A backend that omits or returns invalid object or multipart timestamps cannot
  make those artifacts eligible for age-based deletion; the condition must be
  logged and left to later repair or backend lifecycle.
- Very large prefixes require multiple repair intervals to complete one scan
  cycle. The page size and interval must remain observable and configurable.
- S3-compatible implementations may differ in pagination behavior while objects
  are deleted. Resetting cursors after each complete cycle provides eventual
  re-observation rather than assuming one scan is exhaustive.
