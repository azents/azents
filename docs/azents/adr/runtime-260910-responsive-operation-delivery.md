---
title: "Responsive Runtime Operation Delivery"
created: 2026-09-10
tags: [runtime, performance, reliability, observability, security, infra]
document_role: primary
document_type: adr
snapshot_id: runtime-260910
---

# runtime-260910/ADR: Responsive Runtime Operation Delivery

This ADR records the material decisions for the confirmed
[Responsive Runtime Operation Delivery Requirements](../requirements/runtime-260910-responsive-operation-delivery.md)
(`runtime-260910/REQ`).

## Context

Foreground Runtime operations currently discover replies by repeatedly reading a
generation-scoped reply stream and sleeping when no row is present. Redis reply
reads also refresh stream retention, so every idle observation cycle performs a
read and a write. Production evidence showed the Runner completing sampled
operations before the Worker observed them, while Redis remained lightly loaded.

The Runtime coordination abstraction already has Redis and in-memory
implementations. Redis clients intentionally allow blocking stream commands without
a socket I/O timeout, and Terminal coordination already uses bounded `XREAD` waits
with authoritative state rechecks. Reply streams are shared by Runner generation,
so independent operation waiters must retain non-consuming cursor replay rather
than claim events through a consumer group.

Runner credentials are signed for one logical Runtime and desired generation.
Control correctly rejects stale credentials, but the Runner currently treats
`UNAUTHENTICATED` like a transient transport failure and reconnects forever with
the same process-start credential. Current Provider lifecycle commands are the only
authority that can mint and inject a current credential.

The repository has no Prometheus exporter or scrape-resource contract. Its current
internal observability precedent is bounded process-local recorders, immutable
snapshots, and structured logs.

## Decisions

### runtime-260910/ADR-D1. Use bounded cursor-based event waits while retaining non-blocking replay

The coordination store exposes a separate bounded reply-wait operation in addition
to the existing non-blocking reply read. The cursor remains opaque outside each
store adapter.

Redis first reads rows already present after the caller cursor. When none exist, it
performs ordinary `XREAD` with a bounded block and then rereads the authoritative
stream range after the cursor. In-memory coordination checks under the stream
condition lock and waits for append notification under the same lock.

Each wait is bounded by the smaller of the operation's remaining deadline and one
second. A block timeout is a reconciliation signal: the caller reevaluates the
deadline and cancellation predicate and may wait again. Task cancellation cancels
the blocking operation and is re-raised.

This satisfies `runtime-260910/REQ-1` and `runtime-260910/REQ-2`.

**Rejected alternatives**

- Retaining fixed-frequency non-blocking reads and sleeps, because idle waiters
  continue creating coordination and Worker scheduling work.
- `XREADGROUP`, because reply events are shared observations and must remain
  independently visible to every operation waiter.
- Infinite blocking reads, because deadline, user cancellation, and task
  cancellation must remain bounded.
- Treating wake notifications as completion authority, because cursor-ordered
  stream contents remain the source of truth.

### runtime-260910/ADR-D2. Refresh reply retention only on authoritative append

Reply stream reads and waits do not refresh Redis TTL. Every reply append continues
to refresh the existing retention window, including fenced and operation-aware
append paths.

Request and body stream retention behavior remains unchanged. This decision removes
reply read-side write amplification without creating a new retention contract and
satisfies `runtime-260910/REQ-3`.

**Rejected alternatives**

- Refreshing TTL after every blocking timeout or replay read, because observation
  must remain non-mutating.
- Removing reply TTL entirely, because volatile coordination still needs bounded
  cleanup.
- Changing request and body stream retention in the same delivery, because their
  liveness and consumer semantics are outside the confirmed problem.

### runtime-260910/ADR-D3. Use bounded process-local metrics and structured operational logs

Runtime reply delivery uses one process-local recorder with fixed-cardinality
outcomes and fixed duration buckets. It records active waiters, wait duration,
`event`/`timeout`/`cancel`/`error` outcomes, filtered shared-stream rows, and
reply-append-to-observation latency. A Worker lifecycle sampler records event-loop
timer drift and periodically emits one bounded structured snapshot.

Request, operation, Runtime, Session, Agent, cursor, and payload values are not
metric dimensions. Request-scoped identifiers may appear only in existing or new
structured correlation logs. Health probe response bodies remain unchanged.

This satisfies `runtime-260910/REQ-4` without introducing a new Prometheus
dependency, HTTP scrape contract, or Kubernetes monitoring resource.

**Rejected alternatives**

- Adding Prometheus client, `/metrics`, and monitoring resources in this change,
  because no repository-wide scrape contract currently exists.
- Labeling metrics with operation or Runtime identity, because those dimensions
  are unbounded.
- Extending liveness/readiness payloads with diagnostics, because probe contracts
  are not an observability export surface.

### runtime-260910/ADR-D4. Add an explicit fixed Worker replica value without Worker autoscaling

The Helm chart exposes `server.worker.replicas` with a backward-compatible default
of one. The Worker Deployment renders that value directly.

Redis broker consumer-group delivery, Session ownership leases, and generation
fencing already provide the processing boundary required by more than one Worker.
The chart does not add a Worker HPA, change the default, or modify a live consumer
deployment. This satisfies `runtime-260910/REQ-5`.

**Rejected alternatives**

- Keeping a template hard-code, because operators cannot scale without editing
  rendered output.
- Defaulting to more than one replica, because capacity rollout is operationally
  separate from making the setting available.
- Copying Runtime Control autoscaling to Worker, because Worker scaling signals and
  limits require a separate operational design.

### runtime-260910/ADR-D5. Stop the stale-authority Runner process on rejection

The Runner classifies both registration-time gRPC `UNAUTHENTICATED` and an
accepted stream's rejected heartbeat authority as terminal for the current
process-start credential. It emits bounded credential-rejection evidence, closes
connection-scoped resources through the existing cleanup path, and exits instead
of reconnecting with the same bearer token.

Provider observation and reconciliation remain the credential reacquisition
authority. A subsequent current-generation lifecycle command mints and injects a
fresh Runtime-bound credential while preserving the existing Workspace volume.
Other transport failures keep the current reconnect behavior.

This satisfies `runtime-260910/REQ-6` while preserving the fail-closed credential
and generation rules from
[`runtimeauth-260723/ADR-D5`](runtimeauth-260723-bound-runtime-control-connections.md).

**Rejected alternatives**

- Retrying either authority-rejection path with the same token, because that cannot
  recover and creates an unbounded failure loop.
- Accepting stale desired-generation credentials during reconnect, because that
  weakens Runtime incarnation authority.
- Adding a Runner credential refresh RPC, because current Provider lifecycle
  ownership can recover the process and a refresh protocol would create new secret
  delivery and authorization surfaces.

## Consequences

- Idle foreground operations stop issuing repeated reply read/write cycles.
- One blocked Redis connection is used per active foreground waiter, bounded to at
  most one second before reconciliation.
- A reply appended to a shared generation stream may wake multiple operation
  waiters; each waiter advances its own cursor and filters its own request.
- Redis and memory use different internal cursor and notification mechanisms but
  retain the same observable ordering, deadline, and cancellation behavior.
- Reply retention is driven by liveness writes, not observers.
- Operators gain bounded scheduling and reply-delivery evidence without a new
  monitoring service contract.
- Worker capacity becomes configurable while remaining one replica by default.
- Stale Runner authority fails closed and delegates recovery to Provider
  reprovisioning instead of spinning indefinitely.

## Risks and Mitigations

- **Redis pool occupancy:** concurrent waits hold connections while blocked.
  Targeted concurrency tests and operational snapshots must measure waiter count,
  timeout rate, and completion latency. The bounded wait prevents indefinite pool
  capture.
- **Shared-stream wake amplification:** unrelated replies wake multiple waiters.
  Cursor advancement preserves correctness, and filtered-row counts make the cost
  visible.
- **Redis reset:** prior cursors and in-flight reply state may disappear. Existing
  optional-Redis policy permits in-flight failure but requires a newly empty store
  to accept new work safely; no recovery authority is inferred from missing data.
- **Clock skew:** append-to-observation latency compares timezone-aware event time
  with Worker observation time and clamps negative values to zero. It is
  operational evidence, not protocol authority.
- **Provider recovery delay:** a rejected Runner requires periodic Provider
  observation and a later current lifecycle command, so recovery is eventual
  rather than immediate. Existing lifecycle reconciliation remains the
  retry/recovery owner and exposes failures separately from credential rejection.

## Compatibility and Rollout

- Runtime tool inputs, outputs, errors, operation IDs, generation fencing, and
  final-event authority remain unchanged.
- `read_replies` remains available for non-blocking replay; the new wait operation
  is internal to the coordination abstraction.
- Redis namespace and stored reply payload schema remain unchanged.
- The Helm replica default preserves current rendered behavior.
- No live deployment, merge, synchronization, or Runtime replacement is performed
  by this decision record.
