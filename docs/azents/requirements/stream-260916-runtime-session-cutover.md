---
title: "Runtime Stream Session Naming Cutover Requirements"
created: 2026-09-16
updated: 2026-09-16
tags: [runtime, transport, architecture]
document_role: primary
document_type: requirements
snapshot_id: stream-260916
---

# Runtime Stream Session Naming Cutover Requirements

- Snapshot: `stream-260916`
- Document reference: `stream-260916/REQ`

## Problem

The persistent Runtime transport is currently named and organized as a Runtime Web
session even though its session framing, ownership, relay, flow control, and
bidirectional byte transport are reusable beyond HTTP and WebSocket. Adding file
streaming on top of that contract later would make the transport vocabulary and
protocol identity misleading unless the naming boundary is cut over first.

## Primary Context

### Primary System Outcome

The existing persistent Runtime transport is represented by stream-neutral protocol
and implementation names while its currently supported HTTP and WebSocket behavior
continues to operate unchanged.

## Supporting Scenarios or Effects

- A later file-stream capability can use the already-generalized session boundary
  without another transport-wide rename.
- Mixed old/new Runtime transport peers fail closed at the existing protocol
  fingerprint boundary.
- Runtime Web product, browser, and service-management terminology remains clear
  because this cutover changes the reusable transport layer, not the product
  capability.

## Goals

- Replace Web-specific names for the reusable persistent Runtime session transport
  with stream-neutral names.
- Preserve the exact current HTTP and WebSocket wire behavior, routing, ownership,
  lifecycle, limits, and security semantics.
- Deliver the rename as a hard protocol cutover with no compatibility surface.
- Keep file streaming and file-specific contracts out of this change.

## Non-Goals

- Adding file upload, download, raw-byte transfer, resume, integrity, or file API
  behavior.
- Changing Runtime Web browser policy, public APIs, service rows, Gateway product
  terminology, or numeric-loopback application behavior.
- Changing PostgreSQL Owner-route persistence, lease semantics, capacity semantics,
  or the one-hop Control relay topology.
- Changing ordinary Runtime operations, Terminal, or the existing separate file
  transfer capability.
- Retaining aliases, dual protocol names, compatibility readers, or mixed-version
  fallback for the removed names.

## Requirements

### REQ-1. Stream-neutral transport contract

The reusable persistent Runtime session protocol, generated surfaces, and
transport-layer implementation names must describe a generic stream session rather
than a Web-only session.

**Acceptance criteria**

- Protocol source, generated modules, RPC service names, message names, enum names,
  and transport-layer Python imports use the approved stream-neutral vocabulary.
- Active source and generated-code searches contain no old `RuntimeWebSession`
  transport symbols or old protocol module path.
- Product-facing Runtime Web API and Gateway capability names remain unchanged.

### REQ-2. Preserved HTTP and WebSocket behavior

Current HTTP and WebSocket Runtime Web sessions must remain behaviorally equivalent
after the naming cutover.

**Acceptance criteria**

- Existing HTTP request/response, SSE, WebSocket frame, multiplexing, flow-control,
  scheduler, capacity, drain, heartbeat, and failure tests pass.
- Owner lookup, local-vs-relay routing, Runner attachment, generation fencing, and
  numeric loopback destination rules are unchanged.
- No application bytes are newly persisted, logged, or routed through Redis.

### REQ-3. Clean protocol cutover

The renamed contract must use the existing exact protocol fingerprint boundary and
must not accept the old contract alongside the new one.

**Acceptance criteria**

- The canonical fingerprint changes because the protocol descriptor identity changes.
- Peers using different fingerprints fail before application stream admission.
- No old-name alias, compatibility parser/writer, negotiation list, feature flag, or
  address fallback exists.

### REQ-4. Explicitly deferred file extension

This change must leave a clean, reusable session boundary for a subsequent file
stream feature without implementing that feature now.

**Acceptance criteria**

- No file-specific protocol messages, stream modes, API routes, storage paths,
  transfer state, resume fields, or file tests are added.
- The follow-up file work can depend on the renamed session contract without
  reverting the cutover.

## Fixed Constraints

- The existing Runtime Web behavior and public product surface are preserved.
- The existing Owner route and one-hop relay remain authoritative.
- The cutover is delivered as one independent change before file-stream work.
- The repository's generated protobuf workflow remains the source of generated
  Python modules and stubs.
- No live Kubernetes mutation is part of this change.

## Open Assumptions

- The stream-neutral names will be applied to the reusable transport/protocol
  boundary while Web-specific application adapters retain product-appropriate names.
- Existing generated-code consumers are all in this repository and can be changed in
  the same cutover.

## Confirmation

Confirmed by the requester on 2026-09-16 through the instruction to complete the
generalization cutover independently before adding file support.
