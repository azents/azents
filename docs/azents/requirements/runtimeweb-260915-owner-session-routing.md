---
title: "Runtime Web Owner Session Routing Requirements"
created: 2026-09-15
updated: 2026-09-15
implemented: 2026-09-15
tags: [runtime-web, reliability, architecture]
document_role: primary
document_type: requirements
snapshot_id: runtimeweb-260915
---

# Runtime Web Owner Session Routing Requirements

- Snapshot: `runtimeweb-260915`
- Document reference: `runtimeweb-260915/REQ`

## Problem

A Runner receives a Runtime Web session offer from the Control process that owns the
current Runtime Web epoch, but the current contract lets the offer select a separate
network destination for the Runner Web connection. Service routing can send that
connection to another Control replica, while direct Pod routing couples correctness
to Pod addressing. Either outcome makes destination addressing an unnecessary and
fragile part of an already established ownership relationship.

## Primary Context

### Primary System Outcome

When a current Runner accepts a Runtime Web session offer, the resulting persistent
Web session is attached to the exact Control ownership context that issued the offer,
without relying on an offered Pod or Service destination to recover that context.

## Supporting Scenarios or Effects

- Horizontal Control scaling does not change Runner-to-Owner session correctness.
- Control Pod replacement does not require a per-Pod Runner routing contract.
- Operators do not configure a second Runner Web destination or TLS name in addition
  to the ordinary Runner Control connection.

## Goals

- Make Runner Web session establishment structurally follow the existing authenticated
  Runner-to-Control ownership relationship.
- Remove destination-selection authority from Runtime Web session offers.
- Preserve the existing Runtime Web authority, security, lifecycle, and bounded data
  plane semantics.

## Non-Goals

- Changing Gateway-to-Control routing or the optional one-hop Control relay.
- Changing persisted Runtime Web route ownership, lease, or capacity semantics.
- Changing Runtime Web HTTP, SSE, WebSocket, loopback, or browser policy behavior.
- Changing Terminal or file-transfer channel topology.
- Adding a compatibility fallback for mixed Runtime Web protocol versions.
- Deploying to or mutating a live Kubernetes environment as part of this correction.

## Requirements

### REQ-1. Exact Owner session attachment

A Runner Web session accepted from an offer must attach to the same current Control
ownership context that issued the offer.

**Acceptance criteria**

- Control Service load balancing cannot redirect the offered Runner Web session to a
  different replica.
- No per-Pod address is required to preserve exact Owner attachment.
- A stale Owner epoch, lease, nonce, desired generation, or Runner generation remains
  rejected before application traffic is admitted.

### REQ-2. Authority-only session offers

A Runtime Web session offer must carry only the authority and bounded-handshake data
needed to join the current Owner epoch; it must not select a network destination or
transport identity for a new connection.

**Acceptance criteria**

- The Runner offer contract has no Control replica, connect-address, or TLS-server-name
  destination fields.
- Backend settings and deployment configuration have no Runner-Web-specific Control
  destination or TLS-name values.
- Generated protocol surfaces and tests contain no compatibility reader or writer for
  the removed destination fields.

### REQ-3. Preserved security and lifecycle boundaries

The correction must preserve the current authenticated Runner identity, exact Owner
epoch, protocol fingerprint, bounded join deadline, one-time nonce, session profile,
heartbeat, generation replacement, failure teardown, resource ceilings, and
numeric-loopback destination rules.

**Acceptance criteria**

- Existing Runner Web session authority and transport-state tests continue to pass
  after destination routing is removed.
- Runtime Web application bytes remain absent from ordinary Runner operations,
  PostgreSQL, Redis, Chat items, audit history, and ordinary logs.
- Loss of the ordinary Runner Control connection closes its attached Runner Web
  session before that channel is discarded.

### REQ-4. Clean protocol cutover

The changed offer contract must use the existing exact Runtime Web protocol
fingerprint boundary rather than accepting an ambiguous mixed-version session.

**Acceptance criteria**

- The canonical protocol fingerprint changes with the contract.
- Peers with a different fingerprint fail closed.
- No legacy fields, aliases, negotiation list, or address-based fallback remains.

## Fixed Constraints

- Runtime Web continues to use the existing Runner-authenticated Control listener and
  Runtime credential.
- Gateway ingress may still reach a non-Owner Control and use at most one existing
  Control-to-Control relay.
- PostgreSQL remains the source of truth for the current Runtime Web Owner route and
  lease epoch.
- The correction is delivered as a follow-up PR against `main` after the Phase 1 robust-routing PR was merged.

## Open Assumptions

- The ordinary Runner Control gRPC channel supports concurrent RPC streams, as
  provided by the current gRPC transport and generated stubs.
- Existing Runtime Web E2E fixtures can validate the contract removal without live
  cluster mutation.

## Confirmation

Confirmed by the requester on 2026-09-15 through the instruction to replace the
address-based Runner Web routing structure after the minimal robust-routing phase.
