---
title: "Heavy-Workload Runtime Web Services Requirements"
created: 2026-09-14
updated: 2026-09-14
implemented: 2026-09-14
tags: [runtime-web, transport, performance, reliability]
document_role: primary
document_type: requirements
snapshot_id: runtimeweb-260914
---

# Heavy-Workload Runtime Web Services Requirements

- Snapshot: `runtimeweb-260914`
- Document reference: `runtimeweb-260914/REQ`

## Problem

Runtime Web can proxy bounded HTTP, server-sent event, and WebSocket exchanges, but
its current request-scoped transport and verification evidence do not establish that
asset-heavy development servers, large uploads and downloads, high concurrency, and
long-lived mixed traffic remain usable under sustained load. The system also lacks a
confirmed Runtime-scoped capacity model and operational evidence that the Gateway can
scale horizontally without weakening approval, isolation, revocation, or failure
semantics.

## Primary Context

### Primary System Outcome

An approved Runtime Web endpoint serves an asset-heavy development application,
large streaming transfers, server-sent events, and WebSockets concurrently. As load
increases, the service preserves responsive independent streams, prompt authority
control, bounded resource consumption, Runtime-level isolation, and predictable
failure behavior while Gateway replicas scale independently.

## Supporting Scenarios or Effects

- A Storybook-class development server completes a cold load containing many small
  and medium assets without request setup becoming the dominant bottleneck.
- A user uploads or downloads a large payload while small assets, API calls, SSE, and
  WebSocket traffic remain responsive.
- Gateway replicas scale out, drain, restart, and scale in without requiring sticky
  routing for correctness.
- Multiple endpoints, Sessions, users, and Gateway replicas that reach the same
  Runtime consume one shared Runtime capacity budget.
- One overloaded Runtime does not exhaust the capacity reserved for another Runtime
  or block transport control traffic.

## Goals

- Support asset-heavy, high-concurrency, large-stream, SSE, and WebSocket workloads
  within declared capacity limits.
- Prevent per-request transport setup, serialization, coordination, and authority
  maintenance from becoming the dominant cost at the reference workload.
- Preserve bounded memory, end-to-end backpressure, mixed-workload fairness, and
  prompt cancellation and revocation.
- Make Runtime capacity consistent across horizontally scaled Gateway and Runtime
  Control replicas.
- Provide measurable local-owner and one-hop relay performance, failure, scaling,
  and rollout contracts.

## Non-Goals

- Permanent hosting or indefinite exposure approval.
- Replacing Runtime File Transfer or providing object storage through Runtime Web.
- Public raw TCP, UDP, or arbitrary Runtime network access.
- Automatically replaying or resuming an admitted HTTP mutation, SSE event, or
  WebSocket frame after ambiguous transport failure.
- Introducing a frontend/backend service classification, dependency approval model,
  or new service-sharing permission model.
- Extending approval because of traffic, reconnects, Runtime recovery, or transport
  lifetime.
- Persisting application bodies or retaining paths, queries, cookies, authorization
  values, tickets, identity secrets, or other application secrets in telemetry.
- Transparently transforming application payload encoding or weakening existing
  Gateway browser policy and Runner destination policy for performance.
- Mixed old and new Runtime Web transport interoperability, dual-stack protocol
  operation, retained compatibility branches, or fallback to the removed transport.
- Uninterrupted Runtime Web availability during the coordinated clean-cutover
  maintenance interval.
- Rolling back to the removed transport after the destructive cutover boundary;
  post-cutover correction is fix-forward.

## Requirements

### REQ-1. Asset-heavy HTTP service

Runtime Web must serve cold-cache development applications containing many assets
without transport setup or coordination making the application unusable.

**Acceptance criteria**

- A reference cold-cache workload containing 2,000 assets at browser concurrency 64
  completes at least 99.9 percent of requests that are within the configured Runtime
  capacity budget.
- A warm 64 KiB asset workload adds no more than 100 ms local-owner p95 time to first
  byte and no more than 150 ms one-hop-relay p95 time to first byte relative to the
  same direct-loopback workload in the reference environment.
- Requests rejected because the Runtime budget is exhausted receive a bounded,
  distinguishable overload result rather than an application-looking success.
- The workload does not depend on a warm browser cache to satisfy the acceptance
  criteria.

### REQ-2. Large bidirectional HTTP streaming

Runtime Web must incrementally carry large request and response bodies without
complete-body buffering or durable application-body storage.

**Acceptance criteria**

- Both Content-Length and chunked 1 GiB uploads and downloads complete with exact byte
  count and checksum equality in the reference environment.
- Sustained goodput is at least 70 percent of the identical direct-loopback workload
  on the local-owner path and at least 55 percent on the one-hop relay path.
- No Gateway, Runtime Control, Runner, Redis, PostgreSQL, object store, Chat record,
  event, audit record, or ordinary Runtime operation stores a complete application
  body or application-body chunk.
- Transfer memory remains bounded independently of total payload size.

### REQ-3. Bounded flow control and buffering

Slow senders, slow receivers, and bursty peers must apply backpressure without
unbounded memory growth or cross-stream starvation.

**Acceptance criteria**

- When a producer remains ten times faster than its consumer for ten minutes, memory
  use remains bounded and the exchange either progresses under backpressure or ends
  with an explicit bounded failure.
- The reference capacity profile permits no more than 2 MiB of application-byte
  buffering per logical exchange and no more than 64 MiB of aggregate
  application-byte buffering per Runtime while shared capacity coordination is
  healthy.
- Every Gateway, Runtime Control, and Runner enforces a hard local memory envelope.
  Loss or reset of shared capacity coordination may temporarily make the
  cross-replica Runtime aggregate approximate, but cannot remove per-exchange,
  per-session, or per-process safety bounds.
- Control, cancellation, and revocation signals retain bounded delivery capacity
  even while application-data buffers are full.

### REQ-4. Mixed-workload fairness

A bulk or stalled exchange must not make independent small requests or long-lived
control-sensitive streams unusable.

**Acceptance criteria**

- While a 1 GiB transfer saturates the Runtime's configured bulk capacity, p95 latency
  for small API and asset requests remains within two times the same idle-proxy
  workload.
- SSE and WebSocket delivery p95 jitter remains at or below 250 ms in the reference
  mixed workload.
- No single logical exchange can monopolize the Runtime's application-data capacity
  or starve admission, heartbeat, cancellation, or revocation processing.
- Overload affects only work whose declared Runtime capacity is exhausted and does
  not silently drop accepted data.

### REQ-5. Long-lived SSE and WebSocket support

SSE and WebSocket exchanges must remain usable for the full approved lifetime within
declared Runtime limits.

**Acceptance criteria**

- SSE and WebSocket exchanges can remain active for the default one-hour approval
  period without an unrelated shorter transport timeout.
- Sustained SSE and bidirectional WebSocket workloads complete at the configured
  logical-stream and message limits without unintended disconnects.
- Heartbeat, ping, pong, close, cancellation, and authority revocation remain timely
  during concurrent bulk traffic.
- Approval expiration, explicit close, identity revocation, and generation
  replacement terminate affected long-lived exchanges without extending authority.

### REQ-6. Independent authority for every logical exchange

Transport reuse must not turn trusted-peer authentication or one admitted exchange
into authority for another exchange.

**Acceptance criteria**

- Every logical exchange independently validates browser identity, Session access,
  endpoint, cycle, authority revision, close barrier, Runtime, desired generation,
  Runner generation, numeric port, deadlines, and admission.
- Authority or an already-admitted finite-HTTP completion allowance for one exchange
  cannot be inherited by another HTTP, SSE, or WebSocket exchange.
- Generation replacement rejects new obsolete-generation work and terminates existing
  obsolete-generation exchanges.
- Late, duplicate, stale, cross-exchange, and post-terminal application data is
  rejected without reaching another application exchange.

### REQ-7. Existing isolation and destination safety

Heavy-workload support must preserve the current public and trusted transport
security boundaries.

**Acceptance criteria**

- Deployed Gateway-to-Control and Control-to-Control traffic retains role-specific
  authenticated transport and cannot exchange roles.
- Gateway remains the public browser identity, origin, Fetch Metadata, header, cookie,
  and service-host policy enforcement point.
- Runner remains the final destination enforcement point and connects only to the
  requested numeric `127.0.0.1` port with an origin-form target and redirect following
  disabled.
- Per-exchange, per-session, and per-process safety limits cannot be bypassed by
  increasing physical connection or Gateway replica count. A healthy shared
  coordinator also prevents that increase from expanding the Runtime's configured
  soft capacity budget.
- Runtime Pod network isolation and the maximum one trusted Control relay hop remain
  intact.

### REQ-8. Fail-closed termination and bounded cleanup

Transport loss, authority loss, and component failure must end affected work without
unsafe replay, misrouting, or lasting capacity leakage.

**Acceptance criteria**

- Browser abort, cycle close, identity revocation, generation replacement, owner or
  relay loss, and Gateway, Control, or Runner restart never automatically replay an
  admitted request body, SSE event, or WebSocket frame.
- Runner application sockets, process-local queues, and shared admission and route
  capacity are released within ten seconds after confirmed disconnect or authority
  loss.
- A stale owner, transport connection, stream identifier, lease, or generation cannot
  accept new application data after replacement.
- New admissions fail closed while required approval, generation, or routing
  authority is unavailable. Capacity-coordination loss instead uses bounded local
  fallback limits and does not weaken those authorities.

### REQ-9. Horizontally scalable Gateway

Gateway replicas must scale independently without sticky routing or a single replica
becoming correctness authority.

**Acceptance criteria**

- Any healthy Gateway replica returns the same current authorization result. While
  shared capacity coordination is healthy, replicas also converge on the same
  Runtime soft-capacity result.
- Scaling the reference Gateway deployment from two to four replicas preserves
  successful admissions for non-saturated Runtimes while only a saturated Runtime
  receives predictable overload or backpressure results.
- Scale-in first stops new admissions on the draining replica, gives admitted work a
  bounded drain interval, and then terminates remaining work under the no-replay
  contract.
- Gateway drain, crash, or replacement creates no dual ownership, stale admission,
  or requirement for client affinity.
- Autoscaling can use active logical exchanges, Runtime buffered bytes, throughput,
  queue wait, event-loop lag, and memory pressure rather than CPU alone.

### REQ-10. Runtime-scoped resource limits

Runtime is the primary shared resource-accounting and workload-isolation boundary for
Runtime Web capacity.

**Acceptance criteria**

- Logical exchanges, pending opens, HTTP, SSE, WebSocket, application-byte buffering,
  and bandwidth are accounted against the target Runtime across all Sessions,
  endpoints, users, Gateway replicas, and Runtime Control replicas.
- Creating additional endpoints, Sessions, users, or physical connections cannot
  durably increase one Runtime's configured soft budget.
- Per-exchange safety bounds and an installation-wide emergency ceiling may further
  restrict traffic, but endpoint, user, and Agent identity are authorization
  boundaries rather than the primary capacity allocation boundary.
- One saturated or slow Runtime does not consume another Runtime's reserved data or
  control capacity; in the reference overload workload, the unaffected Runtime's
  small-request p95 latency remains within two times its idle-proxy workload.
- Healthy distributed accounting admits no more than the configured Runtime soft
  limit plus an explicitly bounded reservation allowance. During coordinator
  unavailability or empty-state recovery, temporary cross-replica drift is accepted
  while every process remains inside its hard local safety envelope.

### REQ-11. Predictable overload and recovery

The system must shed load before memory exhaustion and recover capacity without
creating a second correctness dependency.

**Acceptance criteria**

- Exhausted stream, byte, bandwidth, or pending-open capacity produces explicit
  admission rejection or backpressure before a component exceeds its configured
  resource envelope.
- Bulk application traffic cannot exhaust capacity reserved for new admission,
  authority checks, heartbeat, cancellation, revocation, and shutdown.
- Redis unavailability or restoration from an empty state does not lose approval,
  generation, or route authority, terminate otherwise-valid active exchanges, or
  make Runtime Web unavailable. New work continues within hard local fallback
  limits, and Runtime soft-capacity usage may temporarily drift until ephemeral
  coordination converges again.
- Every Redis-backed capacity behavior has an equivalent in-memory implementation
  with the same admission, limit, reset, fallback, and observable-result contract.
  Redis-specific availability, persistence, scripting, or data structures cannot be
  required for correct service behavior.
- Gateway, Control, and Runner recovery restores new safe admissions within a bounded
  and observable interval after their required dependencies are healthy.

### REQ-12. Content-free transport observability

Operators must be able to locate throughput, latency, flow-control, capacity,
authority, relay, and lifecycle bottlenecks without retaining application content or
secrets.

**Acceptance criteria**

- Metrics distinguish protocol class, local-owner versus relay path, active logical
  exchanges, Runtime capacity use, admission result, setup phases, time to first byte,
  duration, byte counts, goodput, queue wait and occupancy, cancellation and close
  reason, route renewal, and database admission latency.
- Gateway, Control, and Runner expose sufficient resource evidence to correlate CPU,
  resident memory, event-loop lag, transport connections, logical exchanges, and
  Runtime-level buffering.
- Metric labels, logs, traces, and diagnostics exclude application bodies, paths,
  queries, cookies, authorization values, identity secrets, tickets, join nonces,
  credentials, and raw upstream errors.
- Load and failure tests produce machine-readable results suitable for comparing
  direct loopback, local-owner, and one-hop relay paths over time.

### REQ-13. Coordinated clean transport cutover

The current Runtime Web transport must be completely replaced in one coordinated
maintenance cutover without retaining a versioned protocol, dual-stack path, or
backward-compatibility implementation.

**Acceptance criteria**

- Runtime Web readiness and new admission are disabled before cutover while existing
  finite HTTP, SSE, and WebSocket exchanges follow the confirmed bounded drain.
- Cutover does not proceed until old active tunnels, route and admission leases, and
  request-scoped Runner connections reach zero or their drain deadline forces
  terminal cleanup.
- Gateway, Runtime Control, and Runner serve Runtime Web only when their exact
  replacement-protocol fingerprint matches; a mixed build set fails closed with
  bounded content-free unavailability.
- The replacement removes the old RPCs, protobuf surfaces, per-tunnel persistence,
  request-scoped Runner and relay clients, configuration, compatibility branches,
  tests, fixtures, and generated surfaces in the same development snapshot.
- Stable endpoint URLs, pending requests, approved cycles, close barriers, browser
  identities, Session authorization, and Runtime generation authority survive the
  transport cutover.
- No failed or drained exchange is replayed through either the replacement or removed
  transport.
- After the destructive transport-state migration, recovery is fix-forward; the
  removed transport is not restored as a rollback or fallback path.

### REQ-14. Complete performance and failure evidence

The heavy-workload contract must be verified with reproducible performance,
resource, fault, and browser evidence rather than byte-count-only functional tests.

**Acceptance criteria**

- A machine-readable load harness measures cold and warm asset workloads, 1 GiB
  uploads and downloads, slow peers, mixed workloads, one-hour SSE and WebSocket
  exchanges, Runtime isolation, Gateway scale-out and scale-in, and configured
  overload.
- Fault injection covers browser abort, approval and identity revocation, Runtime and
  Runner generation replacement, owner and relay loss, Gateway, Control, and Runner
  termination, database unavailability, clean-cutover drain, incompatible component
  fingerprint, and fix-forward recovery.
- Full browser E2E covers both authentication modes and uses the real Runtime,
  Runner, Gateway, local owner, and one-hop relay.
- One shared capacity-coordinator conformance suite runs against both Redis and
  in-memory implementations, including empty-state startup, backend loss, fallback,
  recovery, and current-usage convergence.
- Verification proves bounded local memory, correct checksums, declared throughput
  and latency thresholds, prompt cleanup, no unsafe replay, healthy-coordinator
  Runtime quota isolation, bounded degraded-mode drift, and no application-content
  persistence.
- An absence scan proves that the removed request-scoped transport RPCs, protobuf
  messages, persistence, settings, compatibility branches, tests, fixtures, and
  generated surfaces no longer remain.

## Fixed Constraints

- PostgreSQL remains the durable authority for Runtime Web endpoint, request, cycle,
  close, route, and generation fencing. Runtime capacity is an operational soft
  limit and is not durable product authority.
- Runtime desired generation, Provider-observed generation, and Runner generation
  remain independent fences.
- Application bytes remain live transport data and are not written to PostgreSQL,
  Redis, object storage, Chat, events, audit history, or ordinary Runtime operations.
- Redis may own ephemeral distributed Runtime-capacity coordination. Its
  unavailability, restart, or empty-state restoration cannot prevent Runtime Web
  service or require active exchanges to terminate. Hard local resource safety and
  approval, routing, and generation correctness do not depend on Redis.
- Every Redis coordination implementation must retain behaviorally equivalent
  in-memory parity. The in-memory implementation is complete product behavior for
  its declared topology, not a reduced test stub.
- Owner, relay, transport, or generation ambiguity ends affected exchanges without
  transparent replay, request migration, or cross-owner resumption.
- Existing finite approval, Session authorization, role-specific trusted transport,
  numeric loopback destination, origin-form target, no-redirect, and Runtime network
  isolation constraints remain in force.
- Resource use and deadlines remain bounded and configurable within validated ranges.

## Open Assumptions

- The reference benchmark environment and exact hardware allocation will be recorded
  with results so ratio-based thresholds remain comparable.
- Hard per-process fallback ceilings, healthy-coordinator reservation allowance, and
  degraded-mode convergence behavior will be selected during technical design
  without changing Runtime as the primary soft-capacity boundary.
- Application-level cache semantics and payload compression remain unchanged unless
  a later confirmed requirement explicitly changes them.

## Confirmation

Confirmed by the requester on 2026-09-14 before ADR and design decisions began. The
confirmation includes horizontally scalable Gateway replicas and Runtime-scoped
resource limits as part of the required outcome. The requester further confirmed on
2026-09-14 that Runtime capacity is ephemeral operational coordination: Redis loss
or empty-state recovery may temporarily skew shared usage but must not cause service
failure or terminate otherwise-valid active exchanges. The requester also confirmed
on 2026-09-14 that every Redis capacity behavior must have equivalent in-memory
implementation parity. The requester further confirmed on 2026-09-14 that the
request-scoped transport must be cleanly replaced without protocol versioning,
dual-stack operation, backward-compatibility code, fallback, or post-cutover rollback
to the removed implementation.
