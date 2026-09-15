---
title: "Heavy-Workload Runtime Web Services Decisions"
created: 2026-09-14
tags: [runtime-web, transport, performance, reliability, architecture]
document_role: primary
document_type: adr
snapshot_id: runtimeweb-260914
---

# Heavy-Workload Runtime Web Services Decisions

- Snapshot: `runtimeweb-260914`
- Requirements: [runtimeweb-260914/REQ](../requirements/runtimeweb-260914-heavy-workload-services.md)
- Document reference: `runtimeweb-260914/ADR`

## Decision Summary

- `runtimeweb-260914/ADR-D1` — Application data uses generation-fenced persistent
  multiplexed sessions through the trusted Runtime Control data plane.
- `runtimeweb-260914/ADR-D2` — One lease-fenced Owner Control owns each current
  Runner generation's persistent Web data session.
- `runtimeweb-260914/ADR-D3` — The multiplexed protocol uses typed HTTP and
  WebSocket logical frames while application bodies remain opaque bytes.
- `runtimeweb-260914/ADR-D4` — Receiver-issued hierarchical byte credit and fair
  scheduling bound memory while reserving capacity for control traffic.
- `runtimeweb-260914/ADR-D5` — The Owner Control applies ephemeral Runtime soft
  capacity through behaviorally equivalent in-memory and Redis coordinators.
- `runtimeweb-260914/ADR-D6` — The replacement protocol uses a balanced 256 KiB
  data-frame profile, bounded hierarchical windows, and no additional payload
  compression.
- `runtimeweb-260914/ADR-D7` — Sessions use explicit handshake and heartbeat,
  bounded GOAWAY drain, and no active-stream migration or resumption.
- `runtimeweb-260914/ADR-D8` — The request-scoped transport is removed in one
  coordinated clean cutover with exact fingerprint fencing and fix-forward recovery.
- `runtimeweb-260914/ADR-D9` — Product-owned OpenMetrics, dependency-aware probes,
  bounded drain, and multi-signal Gateway scaling form the operational contract.

## Context

The current Runtime Web data plane binds one public HTTP, SSE, or WebSocket exchange
to one Gateway-to-Control RPC, one durable route and admission record, one Runner
open operation, one Runner-to-Control RPC, and, for a remote owner, one additional
Control-to-Control relay RPC. Runner-side gRPC channels and loopback HTTP client
sessions are also created per exchange. Application data is divided into fixed 64
KiB typed frames and passes through shallow bounded process-local queues without an
explicit byte-credit or fairness protocol.

This request-scoped ownership model preserves strong exchange-level authority and
failure isolation, but it repeats setup, database coordination, serialization, and
connection lifecycle work for every asset. Long-lived exchanges also require
periodic Gateway authority checks and Control route renewal. Existing tests prove
functional streaming beyond 64 MiB but do not establish high-concurrency, large
upload, mixed-workload, Runtime-isolated, or horizontally scaled performance.

The confirmed Requirements preserve PostgreSQL approval, route, and generation
authority, exact endpoint fencing, role-specific trusted transport, Gateway browser
policy, Runner numeric-loopback policy, one maximum relay hop, application-byte
non-persistence, Redis/in-memory parity, bounded hard resources, ephemeral Runtime
soft capacity, and no transparent replay after ambiguous failure. Material decisions
in this ADR select a new transport and operational model within those fixed
boundaries.

## runtimeweb-260914/ADR-D1. Use persistent multiplexed sessions through Runtime Control

**Authority:** `runtimeweb-260914/REQ-1`, `REQ-2`, `REQ-4`, `REQ-5`, `REQ-6`,
`REQ-7`, `REQ-8`, `REQ-9`, `REQ-13`.

Application data continues to traverse the dedicated trusted Runtime Control data
plane. Gateway-to-Control, Runner-to-Control, and, when required, the one-hop
Control-to-Control path use persistent transport sessions that carry multiple
independent logical HTTP, SSE, and WebSocket exchanges.

The persistent peer session is transport authority only. Every logical exchange has
its own immutable authority snapshot, admission result, stream identifier, state
machine, deadlines, flow-control state, cancellation, and terminal outcome. A
transport session never makes one exchange's browser identity, Session access,
approval, endpoint, port, generation, completion allowance, or capacity available to
another exchange.

Runner transport sessions are fenced to the authenticated Runtime, desired
generation, and physical Runner generation. A generation replacement rejects new
opens and ends obsolete-generation logical exchanges. A lost or ambiguous transport
session ends its active exchanges without transparent replay, migration, or
resumption; only a fresh client request may receive a new admission.

This replaces per-exchange Runner gRPC channel creation, Runner join, and loopback
HTTP client-session creation as the steady-state data path. Persistent loopback
connection reuse is allowed only inside the same current Runner generation and
continues to enforce the exact numeric loopback destination and request policy for
every exchange.

**Consequences**

- Runtime Control remains on the application-byte path and must provide bounded
  aggregate buffering, per-exchange flow control, fair scheduling, and reserved
  control capacity.
- The design can retain the existing outbound Runner connection and Runtime Pod
  NetworkPolicy model while removing repeated transport setup from asset fan-out.
- Horizontal Gateway scaling does not require direct inbound connectivity to Runtime
  Pods or sticky browser routing.
- Protocol negotiation, session ownership, routing epochs, frame contracts, Runtime
  capacity leases, draining, and v1 removal remain separate decisions in this
  snapshot.

**Rejected alternatives**

- Retain request-scoped streams and only pool channels and HTTP sessions: reduces
  connection setup but preserves per-asset RPC, route, open, join, and authority
  coordination, leaving insufficient architectural margin for the confirmed
  high-fan-out and long-lived workloads.
- Establish a Control-authorized direct Gateway-to-Runner data plane: can remove a
  byte-relay hop, but requires a new inbound Runtime Pod listener, certificate and
  discovery lifecycle, NetworkPolicy surface, and direct revocation path. That
  security and operational expansion is not justified while a persistent reverse
  path can meet the confirmed workload contract.

## runtimeweb-260914/ADR-D2. Use one lease-fenced Owner Control per Runner generation

**Authority:** `runtimeweb-260914/REQ-6`, `REQ-7`, `REQ-8`, `REQ-9`, `REQ-10`,
`REQ-11`, `REQ-13`; ADR-D1.

Exactly one Runtime Control process owns the persistent Web data session for one
current `(Runtime ID, desired generation, Runner generation)` tuple. After the
Runner generation is authenticated and accepted, the Runner proactively establishes
two outbound persistent connections to the same Owner Control boot:

- the existing operation and lifecycle connection, which remains metadata-only for
  Runtime Web; and
- the Web data session selected by ADR-D1, which carries multiplexed application
  exchanges.

PostgreSQL persists only metadata required to fence and resolve the session owner:
the exact Runtime and generations, owner replica, random owner boot identity,
session lease identity and generation, trusted address, bounded deadlines, and
current lease expiration. The application frames and logical-stream state remain
process-local. Owner acquisition and renewal require the exact current generation
and lease epoch so a process restarted at the same address cannot inherit the prior
session's authority.

Gateway replicas remain active-active and require no client affinity. A Gateway may
send a new logical exchange through any healthy Control replica. That Control either
dispatches to its local owned session or resolves the exact live Owner epoch and
relays the exchange once to the Owner. An Owner never relays onward, and a relayed
open is accepted only when its complete Owner boot and lease epoch still match.

Owner or session loss ends every logical exchange attached to that session without
transparent replay, migration, or resumption. The Runner may establish a new
Owner-session epoch after the obsolete lease can no longer be authoritative. Only a
freshly admitted client request may open work on the new epoch.

**Consequences**

- Gateway scaling changes public admission capacity without multiplying Runner
  sessions or the target Runtime's resource budget.
- Each current Runner generation has one unambiguous application-data owner and one
  bounded relay path.
- Owner failure has a larger transport blast radius than a per-request tunnel, so
  per-exchange reset, fail-closed session teardown, rapid capacity release, and
  deterministic reconnect evidence are required.
- PostgreSQL owner lookup is not required for every application-data frame; it is
  authority for session acquisition, logical-open routing, lease renewal, and
  failure fencing.
- The protocol must prioritize session and stream cancellation so data saturation
  cannot delay owner invalidation.

**Rejected alternatives**

- Let one Runner generation maintain active Web data sessions with multiple Control
  replicas: can reduce relays but creates active-active ownership, duplicate-open,
  quota, revocation, and split-brain complexity at the Runtime boundary.
- Add a separate transport-router service: isolates data-plane scaling from Runtime
  Control but introduces another availability boundary, trusted role, deployment,
  routing authority, and migration surface without removing the need to consume
  current Control generation evidence.

## runtimeweb-260914/ADR-D3. Preserve HTTP and WebSocket semantics in typed logical frames

**Authority:** `runtimeweb-260914/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`,
`REQ-6`, `REQ-7`, `REQ-8`, `REQ-12`, `REQ-13`; ADR-D1, ADR-D2.

The persistent Web data session carries a typed multiplexed protocol rather than raw
HTTP bytes or a nested HTTP/2 connection. Session frames establish and close the
authenticated generation-fenced peer session. Logical-exchange frames represent:

- open, accept, reject, reset, cancellation, and terminal state;
- normalized request and response heads;
- opaque application-data chunks and directional end;
- receiver-issued flow-control credit;
- WebSocket text, binary, continuation, ping, pong, and close semantics; and
- session heartbeat, graceful refusal of new work, and bounded protocol errors.

Application body bytes are not interpreted, transformed, compressed by this
protocol, or persisted. SSE remains an HTTP response whose normalized content type
selects long-lived authority and lifecycle rules; it does not receive an event
storage, cursor, or replay protocol.

Each logical exchange receives a connection-scoped stream identifier that is never
reused within the session epoch. An open must be accepted before application data is
valid. Direction, frame kind, sequence, aggregate size, WebSocket message state,
deadline, cancellation, and terminal state are validated independently for every
stream. Late, duplicate, cross-stream, post-terminal, and pre-acceptance data cannot
reach the Runtime application.

The Gateway remains the HTTP and browser-policy termination point. It authenticates
the browser and applies Host, Origin, Fetch Metadata, CORS, cookie, redirect,
reserved-header, hop-by-hop-header, and response-security policy before or after the
trusted exchange as applicable. The Runner remains the loopback HTTP and WebSocket
termination point and reconstructs each accepted request only for its exact numeric
`127.0.0.1` port and origin-form target with redirect following disabled.

A malformed frame whose stream identity and boundary remain unambiguous resets only
that logical stream. Peer authentication loss, session framing corruption, reused or
ambiguous stream identity, generation mismatch, or state that can no longer be
attributed to one stream closes the entire session and all attached streams without
replay.

**Consequences**

- Existing browser, header, redirect, cookie, SSE, and WebSocket security semantics
  remain explicit and independently testable.
- Headers and control state still require serialization, but application bodies
  remain byte-preserving and can use larger negotiated data frames selected by a
  later decision.
- Per-stream latency, time to first byte, bytes, flow-control stalls, reset reason,
  and terminal outcome can be observed without inspecting application content.
- Flow-control windows, fairness scheduling, concrete frame and message bounds, and
  compression policy remain separate decisions in this snapshot.

**Rejected alternatives**

- Tunnel raw HTTP/1.1 bytes per logical stream: appears to reduce semantic framing
  but requires both ends to parse request and response boundaries, chunking,
  trailers, upgrades, hop-by-hop fields, redirects, cookies, CORS, and WebSocket
  frames again. Framing ambiguity would have a larger cross-stream security impact.
- Run an inner HTTP/2 connection inside the trusted session: supplies a standard
  stream and window model but adds nested framing, HTTP/2-to-loopback-HTTP
  translation, extended-CONNECT WebSocket handling, and a second policy model while
  the outer transport already supplies authenticated delivery.

## runtimeweb-260914/ADR-D4. Use hierarchical byte credit and fair scheduling

**Authority:** `runtimeweb-260914/REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`,
`REQ-8`, `REQ-10`, `REQ-11`, `REQ-12`; ADR-D1, ADR-D2, ADR-D3.

Application data is flow-controlled by explicit receiver-issued byte credit at both
the logical-stream and persistent-session levels. A receiver increases credit only
after its downstream consumer has released the corresponding bytes. Receiving a
frame into another process-local queue does not by itself count as consumption.

Every hop terminates and enforces its own downstream credit:

- the Gateway grants response credit as the browser consumes or releases bytes;
- Runtime Control and the optional relay grant credit only within their downstream
  stream and session windows; and
- the Runner grants request credit as the loopback application consumes bytes and
  grants response data only within credit ultimately propagated from the browser
  path.

A sender cannot transmit application data beyond both the stream window and the
session aggregate window. Exhausted credit applies backpressure instead of dropping
accepted bytes or accumulating an unbounded queue. The Runtime-scoped soft-capacity
coordinator selected by a later decision is an additional upper bound; local window
availability never creates shared Runtime capacity.

Each session has separate bounded capacity for protocol and authority control.
Cancellation, reset, graceful refusal of new streams, heartbeat, credit update,
generation invalidation, owner loss, and authority revocation do not wait behind
application-data credit or the application-data scheduler.

Within application data, a weighted deficit round-robin scheduler gives each active
logical stream bounded progress without allowing a large or stalled stream to
monopolize the writer. Request and response heads, terminal frames, bounded SSE
events, and WebSocket control frames use a bounded latency-sensitive lane. That lane
has independent size and rate limits so an application cannot label unlimited bulk
traffic as priority work. Ordinary body and WebSocket data use the fair data
scheduler.

Credit updates are monotonic within a direction and session epoch and are bounded
against overflow. Duplicate, decreasing, cross-stream, post-reset, post-terminal, or
epoch-mismatched updates are protocol violations. A stream-level violation resets
the exact attributable stream; session-level credit ambiguity closes the session
without replay.

**Consequences**

- Memory is bounded independently of total upload, download, SSE, or WebSocket
  lifetime.
- A slow browser or loopback application propagates backpressure through every relay
  hop instead of causing intermediate complete-body buffering.
- Small assets, API responses, SSE events, WebSocket control, cancellation, and
  revocation retain bounded service while bulk traffic is saturated.
- The implementation must measure granted, consumed, outstanding, and stalled
  credit plus scheduler wait without retaining application content.
- Concrete frame size, initial and maximum windows, latency-lane limits, and update
  thresholds remain a later decision.

**Rejected alternatives**

- Rely only on bounded asynchronous queues and round-robin writes: does not expose
  actual downstream consumption, permits hidden transport buffers, and can block a
  shared writer behind one stream or relay hop.
- Use one connection-level byte window without stream windows: bounds aggregate
  memory but allows one bulk or malicious stream to consume all credit and starve
  independent traffic within the same Runtime.

## runtimeweb-260914/ADR-D5. Use an owner-scoped ephemeral capacity coordinator

**Authority:** `runtimeweb-260914/REQ-3`, `REQ-4`, `REQ-8`, `REQ-9`, `REQ-10`,
`REQ-11`, `REQ-12`, `REQ-14`; ADR-D2, ADR-D4.

Runtime Web capacity is an ephemeral operational soft limit, not durable approval,
routing, generation, or security authority. The single Owner Control selected by
ADR-D2 is the decision point for the current Runtime and Runner generation's shared
stream, buffered-byte, pending-open, and inbound and outbound bandwidth capacity.

After browser and Session authority succeeds, a Gateway sends a bounded logical-open
admission to the Owner before reading more than its hard pre-admission request-body
allowance. The Owner accepts or rejects the open and issues the stream and session
credit allowed by ADR-D4. All Gateway and relay paths for the Runtime therefore
consume the same Owner-scoped soft budget without client affinity or per-Gateway
partitioning.

The capacity coordinator exposes one backend-neutral contract for:

- admitting and releasing logical HTTP, SSE, and WebSocket exchanges;
- reserving and releasing bounded buffer grants for each participating process;
- issuing bounded inbound and outbound bandwidth grants;
- reporting current aggregate and per-class usage without application content; and
- resetting or reconstructing ephemeral coordination state.

The in-memory and Redis implementations have behaviorally equivalent admission,
limit, reset, fallback, and observable-result semantics and run the same conformance
suite. The in-memory implementation is complete behavior for the declared topology,
not a reduced test stub. Gateway, relay, and Runner processes do not access Redis
directly; they receive bounded grants through the Owner's typed protocol.

The Owner's process-local active-stream registry and D4 outstanding-credit state
remain available if Redis becomes unavailable. The Owner continues existing streams
and new admissions under hard local process, session, stream, and pre-admission
ceilings while the shared soft-capacity view may temporarily drift. It does not end
valid streams, fail Runtime Web solely because Redis is unavailable, or weaken
approval, route, or generation checks.

When Redis starts empty or returns after interruption, the Owner begins a fresh
capacity-backend epoch and republishes current aggregate usage from its live
process-local registry. Stale Redis keys or grants are never trusted as current
authority. New admission may be temporarily throttled while usage converges, but
existing valid streams continue. If the Owner itself is lost, ADR-D2 ends the
session's streams and the replacement Owner starts with a new session and capacity
epoch.

PostgreSQL stores no Runtime capacity counters, token buckets, buffer grants, or
capacity history. It continues to own endpoint, cycle, close, route, owner-session,
and generation authority. Every process enforces hard local resource ceilings
independently of the soft coordinator so temporary cross-replica skew cannot become
unbounded memory use or remove protocol safety.

**Consequences**

- Redis persistence, HA, availability, and implementation-specific scripting are not
  required for correct or available Runtime Web behavior.
- Gateway horizontal scaling cannot intentionally increase a healthy Owner's Runtime
  soft budget, while degraded coordination may temporarily skew aggregate use within
  hard local ceilings.
- Capacity recovery does not replay application work or terminate otherwise-valid
  active streams.
- Shared capacity decisions add no PostgreSQL transaction to the data-frame path and
  require only bounded Owner-local operations in the normal path.
- The Design must define backend switching, current-usage publication, hard local
  fallback ceilings, soft-limit convergence, and identical Redis/in-memory tests.

**Rejected alternatives**

- Persist exact capacity leases and bandwidth tokens in PostgreSQL: makes an
  operational soft limit durable, adds database work to high-rate admission and
  refill paths, and is unnecessary when reset and temporary drift are acceptable.
- Make Redis the only capacity implementation or fail service when Redis is
  unavailable: violates the required in-memory parity and turns ephemeral overload
  coordination into a service availability dependency.
- Divide one Runtime budget statically among Gateway replicas: wastes idle capacity,
  changes effective behavior during scale events, and cannot coordinate the Owner,
  relay, and Runner buffer domains consistently.

## runtimeweb-260914/ADR-D6. Use a balanced uncompressed transport profile

**Authority:** `runtimeweb-260914/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`,
`REQ-10`, `REQ-11`, `REQ-14`; ADR-D3, ADR-D4, ADR-D5.

Runtime Web protocol v2 uses the following initial interoperable data profile:

- every v2 peer supports a 256 KiB application-data frame;
- a peer may advertise 512 KiB support, which is used only when every hop for the
  logical exchange accepts it;
- one serialized transport envelope is at most 1 MiB including typed metadata;
- normalized request and response header limits retain the configurable 32 KiB
  default and 128 KiB hard maximum;
- an ordinary non-head control frame is at most 16 KiB; and
- every persistent session reserves 256 KiB outside application-data windows for
  bounded control traffic.

A logical exchange has an initial and maximum outstanding application-data window of
1 MiB in each direction. Full-duplex outstanding application data is therefore
bounded to 2 MiB per stream. A persistent hop session has an initial and maximum
window of 8 MiB in each direction and a combined 16 MiB bound. The Owner may grant a
smaller effective session window to satisfy the current D5 Runtime capacity profile
and every process's hard local envelope.

A receiver sends credit after consuming at least half of its current window or after
ten milliseconds when any consumed credit remains unreported. This limits update
overhead for bulk traffic while returning capacity promptly for small assets, SSE,
and WebSocket traffic.

WebSocket application messages remain limited to 1 MiB. Text validation, control
frame limits, close semantics, and fragmentation state remain explicit. The public
Gateway parser uses the same 1 MiB message limit so it does not appear to accept an
8 MiB message that the trusted transport later rejects.

The validated Runtime Web request-body upper bound is 1 GiB and may be configured
lower by an installation. Responses do not gain a complete-body byte cap; their
approval and transport deadlines, Runtime bandwidth, hierarchical credit, and hard
local memory limits remain authoritative. Neither direction buffers a complete
body.

Protocol v2 does not apply custom payload compression, gRPC message compression to
application-data frames, or WebSocket per-message compression. Existing application
`Content-Encoding` bytes are forwarded unchanged. This avoids redundant work for
already-compressed assets, removes shared compression-state risk, and keeps
post-decompression resource accounting outside the trusted transport.

**Consequences**

- A 1 GiB body uses 4,096 data frames at the mandatory 256 KiB size instead of
  16,384 current 64 KiB frames.
- Optional 512 KiB frames provide a benchmarked throughput path without making large
  frames mandatory for every hop.
- Stream and session windows fit the confirmed 2 MiB per-stream and coordinated
  64 MiB per-Runtime reference buffering profile.
- The implementation must configure underlying gRPC message limits above the 1 MiB
  envelope plus protocol overhead without exposing a larger accepted protocol
  envelope.
- Numeric changes after acceptance require evidence that the approved profile cannot
  meet Requirements rather than silent tuning during implementation.

**Rejected alternatives**

- Use 1 MiB data frames, 4 MiB directional stream windows, 32 MiB directional
  session windows, and 8 MiB WebSocket messages: reduces frame count further but
  increases writer occupancy, memory reservation, relay burst size, and
  small-stream latency beyond the confirmed reference envelope.
- Retain 64 KiB frames, 256 KiB directional stream windows, and 4 MiB directional
  session windows: is memory-conservative but preserves the frame and scheduling
  overhead that the heavy-workload snapshot exists to remove.
- Add transport or WebSocket payload compression: increases CPU and memory
  variability, often recompresses already-compressed development assets, and creates
  a separate decompression-bound contract without improving byte preservation.

## runtimeweb-260914/ADR-D7. Use explicit non-resumable lifecycle and bounded drain

**Authority:** `runtimeweb-260914/REQ-2`, `REQ-5`, `REQ-6`, `REQ-8`, `REQ-9`,
`REQ-11`, `REQ-13`, `REQ-14`; ADR-D1, ADR-D2, ADR-D3, ADR-D4.

A Runner Web data session begins with an explicit hello carrying the Runtime ID,
desired generation, Runner generation, protocol version and capabilities, random
session nonce, and proposed frame and window profile. The Owner validates the
authenticated Runner credential, exact current generations, and exact Owner lease
before returning the accepted Owner-session epoch and effective profile. The
handshake must complete within ten seconds, and no logical open or application data
is valid before acceptance.

Every logical exchange follows explicit open, accepted or rejected, directional
data, directional end, reset, and terminal states. Application data is invalid
before open acceptance and after reset or terminal state. HTTP uploads and responses
support independent half-close. WebSocket directions and close state remain
independent until the typed close handshake or reset completes. Stream identifiers
are never reused in one session epoch.

Session heartbeat is independent from application activity. Peers exchange heartbeat
and acknowledgement every five seconds and treat two consecutive missed intervals
or an observed transport failure as session loss within ten seconds. Authority and
generation invalidation is signalled immediately; a five-second fallback
revalidation bounds missed invalidation so affected streams close within the
confirmed ten-second revocation boundary.

A planned Gateway drain:

- makes readiness false and stops new browser admission first;
- sends a graceful refusal of new logical streams with the last accepted stream ID;
- allows already-started finite HTTP exchanges to complete for at most 120 seconds
  and never beyond their approval or transport deadline;
- gracefully closes SSE and WebSocket exchanges within five seconds with a
  service-drain reason; and
- resets any remaining streams when the drain grace expires before process exit.

Other Gateway replicas continue new admission without client affinity.

A planned Owner Control drain follows the same stream grace, rejects new opens, and
retains the exact Owner lease only while draining existing work. After all streams
end or grace expires, it releases the session lease and closes the Runner session.
The Runner then establishes a new Owner-session epoch. D2 remains strict: old and
new Owners do not simultaneously accept new streams. Requests arriving during the
bounded handoff receive a content-free unavailable result and are not automatically
replayed.

Finite HTTP receives a default 30-minute transport deadline that may be configured
lower and can never exceed approval expiry. SSE and WebSocket have no unrelated
shorter application-idle timeout and may remain active until approval expiry.
Registration, open acceptance, session heartbeat, transport, approval, drain, and
revocation deadlines remain separate typed values.

Owner loss, peer-authentication loss, session framing or credit ambiguity, and
desired or Runner generation replacement close the session and all attached
streams. Generation replacement forbids new opens immediately rather than using the
planned finite-HTTP drain allowance. Explicit exposure close and identity revocation
cancel affected streams immediately. No active HTTP, SSE, or WebSocket exchange is
migrated, resumed, or replayed on another session; a new epoch accepts only a fresh
browser request.

**Consequences**

- Planned Gateway scale-in gives finite transfers a bounded completion opportunity
  while keeping Pod termination finite.
- Planned Owner replacement may create a bounded Runtime-specific new-request
  interruption because single ownership is preserved instead of overlapping epochs.
- Long-lived SSE and WebSocket traffic no longer inherits the current ten-minute
  HTTP transport window but still ends at approval expiry or bounded drain.
- Session, stream, approval, transport, and drain failures have distinct
  content-free reasons for metrics and client-visible closure.
- Kubernetes termination grace, readiness, preStop, and process shutdown must be
  aligned with the accepted 120-second and five-second drain behavior.

**Rejected alternatives**

- Immediately terminate every stream during planned drain: simplifies process exit
  but unnecessarily interrupts valid large finite transfers and makes graceful
  rollout indistinguishable from failure.
- Resume or hand off active streams to a new Owner session: requires replay buffers,
  byte acknowledgements, overlapping ownership, and application-effect inference
  that conflict with no-persistence and no-replay boundaries.

## runtimeweb-260914/ADR-D8. Replace the transport in one coordinated clean cutover

**Authority:** `runtimeweb-260914/REQ-8`, `REQ-9`, `REQ-13`, `REQ-14`;
ADR-D1, ADR-D2, ADR-D7.

The current request-scoped Runtime Web transport is removed and replaced in one
coordinated maintenance cutover. The implementation does not add a v2 capability,
dual-stack protocol, compatibility adapter, fallback branch, or retained disabled
copy of the old transport.

The old `runtime-web-http.v1` capability is removed. The replacement exposes one
current unversioned Runtime Web transport capability and an exact generated protocol
fingerprint in the session handshake. The fingerprint is an equality fence, not a
version-negotiation mechanism: Gateway, accepting Control, Owner Control, relay, and
Runner must use the same fingerprint or Runtime Web remains unavailable with a
bounded content-free mismatch result.

This decision supersedes only the version-label wording in ADR-D6 and ADR-D7.
References there to protocol v2, a protocol version, or negotiated capabilities mean
the single replacement protocol's fixed numeric profile and equality fingerprint.
The implemented handshake carries no supported-version list and negotiates no
backward-compatible protocol variant.

The cutover sequence is:

1. enter Runtime Web maintenance, make Gateway Runtime Web readiness false, and stop
   new exposure data-plane admission without changing durable endpoint or approval
   authority;
2. apply D7 drain to active finite HTTP, SSE, and WebSocket exchanges;
3. verify that old active tunnels, route and admission leases, request-scoped Runner
   connections, and relay calls are zero or force their terminal cleanup at the
   bounded drain deadline;
4. apply the forward schema migration and deploy the replacement Gateway, Runtime
   Control, Runner, generated protocol surfaces, and chart configuration as one
   compatibility set;
5. verify exact protocol fingerprint, Owner-session readiness, Redis and in-memory
   capacity conformance, local-owner and relay smoke traffic, and absence of old
   active state; and
6. restore Runtime Web readiness and new admission.

The replacement snapshot removes:

- request-scoped Gateway Proxy, Runner ConnectWeb, and Control relay RPCs and their
  protobuf messages;
- per-tunnel route and Control/Gateway admission persistence used only by the old
  transport;
- request-scoped Runner gRPC channels, relay channels, and loopback HTTP client
  sessions;
- old frame-size, queue, connection-limit, capability, and transport-selection
  configuration;
- compatibility branches, adapters, feature flags, fallback logic, and dormant old
  implementations;
- old transport unit, integration, E2E, fixture, generated-client, and chart tests;
  and
- stale documentation and generated surfaces that describe or expose those units.

Replacement tests cover the same approved HTTP, SSE, WebSocket, identity, approval,
generation, local-owner, relay, and failure behavior rather than retaining old tests
as compatibility evidence. An absence scan is required before the cutover is
considered complete.

Stable endpoint URLs, pending requests, approved cycles, close barriers, browser
identities, Session authorization, and Runtime generation evidence are durable
product authority and survive maintenance. Ephemeral old transport and capacity
state does not survive and is recreated only in the replacement model. No drained or
failed exchange is replayed.

Before the destructive migration starts, operators may abort maintenance and keep
the old release because no cutover has occurred. After the old transport state and
code cross the destructive boundary, rollback to that transport is unsupported.
Recovery is fix-forward without restoring old RPCs, schema, compatibility code, or
fallback behavior.

**Consequences**

- Runtime Web has a bounded maintenance interruption instead of mixed-version
  availability.
- Runtime Control may continue unrelated Runtime operations during the maintenance
  interval, but its Runtime Web readiness remains disabled until the complete
  fingerprint-matched set is ready.
- Deployment automation must coordinate Gateway, Control, Runner image, migration,
  drain evidence, and readiness rather than relying on ordinary independent rolling
  compatibility.
- The protocol fingerprint prevents accidental mixed builds without creating
  multiple supported protocol versions.
- Cleanup and absence verification are part of the primary implementation, not a
  later optional compatibility-removal phase.

**Rejected alternatives**

- Add versioned v1/v2 dual-stack rollout and per-request transport selection:
  explicitly retains compatibility paths and old transport state that the requester
  requires removed.
- Keep old code and schema disabled for rollback: leaves a dormant fallback and
  continuing maintenance obligation across the clean-replacement boundary.
- Reuse one capability identifier without an exact compatibility fingerprint:
  allows accidentally mixed Gateway, Control, relay, and Runner builds to interpret
  incompatible frames instead of failing closed.

## runtimeweb-260914/ADR-D9. Own transport telemetry and support multi-signal scaling

**Authority:** `runtimeweb-260914/REQ-3`, `REQ-4`, `REQ-8`, `REQ-9`, `REQ-10`,
`REQ-11`, `REQ-12`, `REQ-13`, `REQ-14`; ADR-D4, ADR-D5, ADR-D7, ADR-D8.

Gateway, Runtime Control, and Runner expose product-owned content-free Runtime Web
transport telemetry. Deployed server components publish an internal OpenMetrics
surface without bundling or requiring a cluster-wide Prometheus, Prometheus Adapter,
or KEDA installation.

Gateway autoscaling uses Kubernetes `autoscaling/v2`. The default chart supports CPU
and memory utilization resource metrics and requires corresponding resource requests
when autoscaling is enabled. Scale-up reacts without a long stabilization delay.
Scale-down uses a five-minute stabilization window and the D7 drain path.

Gateway additionally exposes a normalized `runtime_web_gateway_pressure` Pods metric
whose value is the maximum bounded ratio of:

- active browser exchanges to the local hard exchange ceiling;
- Gateway application buffering to the local hard byte ceiling;
- scheduler queue-wait pressure;
- event-loop lag pressure; and
- resident memory to the container memory limit.

Runtime soft-capacity rejection is excluded because adding Gateway replicas does not
increase a Runtime's D5 budget. When an operator provides a compatible Kubernetes
custom-metrics adapter, the chart can add this Pods metric with a target of 0.7.
Without an adapter, CPU and memory HPA remain functional and the pressure metric
remains available for observation. Azents does not install the adapter or monitoring
stack as a Runtime Web dependency.

Every process enforces hard local active-session, logical-stream,
application-buffer, control-buffer, pending-task, and event-loop queue ceilings
independently from HPA and D5 soft capacity. Exceeding a local ceiling applies
bounded admission rejection or D4 backpressure before container memory exhaustion.
Benchmark evidence determines recommended CPU and memory requests and limits; this
ADR does not invent unmeasured resource quantities.

Gateway Runtime Web readiness is true only while:

- the public security and configuration fingerprint is valid;
- the process is outside maintenance and drain;
- PostgreSQL approval and route authority can be queried;
- at least one trusted Control with the exact D8 replacement fingerprint is
  reachable; and
- local hard pressure remains below the readiness rejection threshold.

Redis loss does not make Gateway unready. Liveness checks only process and event-loop
progress and do not restart Pods because PostgreSQL, Control, Redis, or an application
is unavailable. Runtime Control exposes Runtime Web sub-readiness separately from
general Runtime operation readiness so a Web-specific failure does not automatically
remove unrelated Control capability.

Gateway and Control process termination uses `preStop` or the equivalent process
signal to enter D7 drain before exit. Readiness becomes false first. Kubernetes
termination grace is 150 seconds, covering the 120-second finite-HTTP drain plus
cleanup margin. PDB behavior remains enabled. Gateway HPA scale-in uses the same
drain path. The chart defines and validates the Ingress contract required for
WebSocket upgrade, SSE and response streaming, disabled proxy buffering where
required, a 1 GiB request limit when enabled, and timeouts compatible with D7.

Content-free metrics cover:

- active peer sessions and logical streams by protocol and local or relay path;
- open, accept, reject, reset, close, and bounded reason;
- setup phase, time to first byte, duration, byte count, goodput, and frame count;
- stream and session credit, outstanding bytes, stall time, scheduler wait, and
  bounded queue occupancy;
- heartbeat, missed heartbeat, graceful refusal, drain, generation invalidation,
  and Owner-session epoch transition;
- capacity backend, reset, degraded fallback, current-usage publication, and
  convergence;
- event-loop lag, resident memory, and application and control buffering; and
- maintenance state and protocol-fingerprint mismatch.

Metric dimensions remain bounded to protocol, direction, path, outcome, reason,
backend, and similarly low-cardinality categories. Per-Runtime current capacity may
use a gauge only while that Runtime is active and must be removed at zero, or may be
served through an authorized diagnostic projection. User, Session, endpoint, path,
query, header, cookie, authorization, ticket, nonce, credential, body, and raw
upstream error values are never metric labels.

Required pull-request CI covers deterministic protocol state, credit and capacity
conformance, Redis and in-memory parity, bounded concurrent-asset and 64 MiB transfer
fixtures, slow-peer memory bounds, clean-cutover behavior, and old-surface absence.
A dedicated scheduled or release performance gate produces machine-readable evidence
for the complete 2,000-asset, 1 GiB, one-hour SSE and WebSocket, mixed-fairness,
Gateway scale, owner and relay failure, capacity-backend failure, and direct versus
local-owner versus relay workload matrix.

**Consequences**

- Operators receive stable product metrics without a mandatory monitoring-stack
  dependency.
- Default CPU and memory scaling remains deployable on standard Kubernetes, while
  transport-aware scaling becomes available through a standard custom-metrics
  adapter.
- Readiness removes traffic from unhealthy or draining Gateway replicas without
  using dependency failures as a liveness restart signal.
- Long performance tests do not make every pull request prohibitively slow, but the
  replacement cannot complete cutover without the dedicated full-profile evidence.
- Chart, NetworkPolicy, Service, scrape, probe, resource, HPA, PDB, Ingress, and
  termination settings become part of the implementation and verification scope.

**Rejected alternatives**

- Bundle Prometheus Adapter, KEDA, or a monitoring stack as a mandatory Runtime Web
  dependency: expands cluster-wide lifecycle and availability ownership beyond the
  transport and is unnecessary to expose a standard metric contract.
- Retain CPU-only HPA and unconditional readiness: misses long-lived low-CPU stream,
  buffer, memory, queue, Control-connectivity, maintenance, and drain pressure that
  the confirmed horizontal-scaling outcome requires.
