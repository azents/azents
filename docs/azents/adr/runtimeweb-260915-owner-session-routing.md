---
title: "Runtime Web Owner Session Routing Decisions"
created: 2026-09-15
tags: [runtime-web, reliability, architecture, transport]
document_role: primary
document_type: adr
snapshot_id: runtimeweb-260915
---

# Runtime Web Owner Session Routing Decisions

- Snapshot: `runtimeweb-260915`
- Requirements: [runtimeweb-260915/REQ](../requirements/runtimeweb-260915-owner-session-routing.md)
- Document reference: `runtimeweb-260915/ADR`

## Decision Summary

- `runtimeweb-260915/ADR-D1` — Runner Web RPCs reuse the ordinary authenticated
  Runner Control gRPC channel that received the Owner offer.
- `runtimeweb-260915/ADR-D2` — Runner session offers contain join authority only;
  offered destination and TLS-selection fields and their configuration are removed.

## Context

The Runtime Web Owner acquires a lease only for a Runner that is already connected to
that Control process through the ordinary authenticated Runner Control stream. The
Owner sends its one-time session offer over that stream. The implemented Runner then
opens another gRPC channel to an address supplied alongside the offer.

The original heavy-workload decision described two outbound connections to the same
Owner Control boot and selected a direct Pod address to achieve that topology. The
implementation therefore made a second address lookup responsible for recovering an
ownership relationship that the ordinary Control channel already establishes. Direct
Pod addresses couple the Runner to Pod discovery; a stable Service address avoids
that coupling but may choose a different replica and add a redundant relay.

This snapshot corrects that routing mechanism while retaining the authoritative
parts of `runtimeweb-260914`: one lease-fenced Owner, a distinct persistent Runner Web
RPC stream, exact epoch and nonce validation, bounded multiplexing, and at most one
Gateway-side Control relay.

## runtimeweb-260915/ADR-D1. Reuse the ordinary Runner Control gRPC channel

**Authority:** `runtimeweb-260915/REQ-1`, `REQ-3`, `REQ-4`.

The persistent Runner Web RPC is opened as another concurrent HTTP/2 stream on the
same gRPC channel that carries the ordinary Runner Control stream and delivered the
session offer. It remains a distinct `RuntimeRunnerWebSession.Connect` RPC with its
own message flow, session state, backpressure, heartbeat, shutdown, and failure
handling.

The ordinary channel is the routing authority because its remote Control process is
the process that authenticated the Runner, acquired the exact Runtime Web Owner
lease, and issued the offer. The offer's Owner epoch, nonce, deadline, and fingerprint
remain the admission authority for the new Web RPC; channel reuse does not replace
those checks.

The Runner Web session client borrows the shared channel and never closes it. Runner
shutdown and Control reconnection close the Web session before closing the owning
Control client and channel. A new ordinary Control connection creates a new manager
and can accept only a current offer issued on that connection.

This decision replaces the Runner connection mechanism in
`runtimeweb-260914/ADR-D2` that required two independently addressed outbound
connections to the same Owner. The two RPC streams remain, but they share one
transport channel and one authenticated remote endpoint.

**Consequences**

- Service load balancing and Pod addressing are no longer part of offered-session
  correctness.
- Runner Web and ordinary Control share transport failure fate, matching their
  existing ownership and generation lifecycle.
- The shared gRPC channel must permit concurrent generated service stubs and RPC
  streams; this is validated directly in composition and integration tests.
- Runner Web session teardown must not close the shared channel.

**Rejected alternatives**

- Continue opening a second channel through the stable Control Service: removes Pod
  coupling but can route to a non-Owner replica and add a Control-to-Control relay.
- Restore direct Pod routing: reaches the intended replica but requires Pod discovery,
  Pod-address egress policy, and a separate TLS-name contract for no independent
  authority benefit.
- Move Runtime Web frames into the ordinary `ConnectRunner` message stream: would
  combine lifecycle and application-data queues, weaken independent backpressure and
  control-lane isolation, and require a much larger protocol redesign.
- Add a dedicated Runner-side transport router: introduces another authority and
  availability boundary while the existing channel already identifies the Owner.

## runtimeweb-260915/ADR-D2. Remove destination authority from session offers

**Authority:** `runtimeweb-260915/REQ-2`, `REQ-3`, `REQ-4`; ADR-D1.

`RunnerSessionOffer` contains only the exact Owner epoch, one-time session nonce,
protocol fingerprint, and bounded registration deadline. It no longer carries an
Owner replica identifier, connection address, or TLS server name. The persisted
route keeps its Owner replica identifier and trusted Owner address because Gateway
routing and the optional Control-to-Control relay still require those values; they
are not copied into the Runner offer.

The backend removes Runner-Web-specific connect-address and TLS-server-name settings,
validation, constructor parameters, Helm environment variables, and E2E fixture
values. Protobuf field numbers 4, 8, and 9 are reserved after removal so they cannot
be accidentally reused with incompatible meaning.

The generated protobuf descriptor participates in the existing canonical Runtime Web
protocol fingerprint. Removing the fields therefore changes the fingerprint, and the
existing exact-equality rule rejects mixed versions without a compatibility reader,
writer, alias, negotiation list, or fallback.

**Consequences**

- The offer is an authority token rather than a routing instruction.
- Control deployment configuration has one fewer duplicated destination/TLS contract.
- Persisted Owner routing remains unchanged for Gateway-side relay resolution.
- Rolling mixed-version Runtime Web sessions fail closed until both peers use the
  matching fingerprint, consistent with the existing clean-cutover policy.

**Rejected alternatives**

- Retain unused fields temporarily: preserves an incorrect public protocol contract,
  allows destination authority to reappear, and weakens absence verification.
- Keep `owner_replica_id` only as diagnostic metadata: the Owner epoch already has the
  immutable boot and lease identity used for validation, while replica identity is
  neither needed nor trusted by the Runner session join.
- Accept old and new offers during rollout: conflicts with the existing exact
  fingerprint clean-cutover boundary and adds a legacy routing path.

## Decision Ownership

The requester delegated the remaining technical correction by authorizing replacement
of the incorrect merged Runtime Web structure after the minimal Phase 1 fix. The
Agent selected the mechanisms above within the confirmed Requirements and existing
security, authority, and clean-cutover constraints on 2026-09-15.
