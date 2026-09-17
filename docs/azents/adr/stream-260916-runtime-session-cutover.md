---
title: "Runtime Stream Session Naming Cutover Decisions"
created: 2026-09-16
tags: [runtime, transport, architecture]
document_role: primary
document_type: adr
snapshot_id: stream-260916
---

# Runtime Stream Session Naming Cutover Decisions

- Snapshot: `stream-260916`
- Requirements: [stream-260916/REQ](../requirements/stream-260916-runtime-session-cutover.md)
- Document reference: `stream-260916/ADR`

## Decision Summary

- `stream-260916/ADR-D1` — Rename the reusable persistent session protocol and
  transport-layer implementation from Runtime Web Session to Runtime Stream Session
  in one hard cutover.
- `stream-260916/ADR-D2` — Keep Runtime Web product and application-adapter names
  where they describe HTTP/WebSocket exposure rather than the reusable transport.
- `stream-260916/ADR-D3` — Use the descriptor-derived exact fingerprint boundary and
  provide no old-name compatibility path.

## Context

The current persistent session carries HTTP and WebSocket exchanges, but its
envelope, RPC services, generated modules, state machine, flow-control helpers,
Runner client, and relay are named `RuntimeWebSession`. The next planned capability
is file streaming over the same session boundary. Keeping the old vocabulary would
make the shared protocol appear narrower than its intended role and would force a
second protocol-wide rename during file work.

The existing Runtime Web product remains a meaningful application capability:
browser identity, service exposure, HTTP/WebSocket policy, service management, and
Gateway adapters are Web-specific. Those names are not part of this transport
cutover.

## stream-260916/ADR-D1. Rename the reusable session boundary in one cutover

**Authority:** `stream-260916/REQ-1`, `REQ-2`, `REQ-4`.

The protocol file, protobuf package symbols, generated module names, persistent
session services, envelope and frame messages, session state and flow-control
modules, Runner Web-session client/manager wiring, Control relay/broker/owner
transport code, and their tests are renamed to stream-neutral `RuntimeStreamSession`
terminology. Current HTTP and WebSocket protocol enum values remain as payload
protocols inside the generalized stream session.

This is a hard replacement. The old source/module/symbol names are deleted rather
than retained as aliases.

**Rejected alternatives**

- Rename only the `.proto` file: leaves the implementation and generated API
  misleading and causes a second rename when file streaming is added.
- Keep the old class names internally: preserves the wrong abstraction boundary and
  makes absence verification impossible.
- Introduce a generic wrapper around the Web-named protocol: creates two names for
  one wire contract without adding behavior.

## stream-260916/ADR-D2. Preserve Web-specific product adapters

**Authority:** `stream-260916/REQ-1`, `REQ-2`; unchanged Runtime Web spec.

Runtime Web API routes, service-management repositories and models,
`runtime_web_services`, `runtime_web_session_routes`, browser Gateway policy,
HTTP/WebSocket loopback adapters, and product-facing configuration remain
Web-specific. They consume the generalized stream session where appropriate but are
not renamed merely because they use it.

The persisted Owner route remains a Runtime Web route in this phase. A later file
feature may decide whether a shared Owner route abstraction is required; that is
outside this cutover.

**Rejected alternatives**

- Rename every `runtime_web` product/domain identifier: expands a transport
  refactor into a public product and persistence migration with no requirement.
- Rename the persisted route table now: changes durable schema authority before a
  file use case establishes that it is necessary.

## stream-260916/ADR-D3. Enforce exact fingerprint cutover

**Authority:** `stream-260916/REQ-3`; existing clean-cutover constraint.

The canonical protocol fingerprint continues to derive from the generated protobuf
descriptor and fixed protocol inputs. The renamed descriptor changes the fingerprint,
so old and new peers cannot establish a session. No alias, compatibility reader,
dual writer, version negotiation, fallback, or feature flag is introduced.

This keeps deployment rollback whole-build and fail-closed, matching the existing
Runtime transport policy.

## Decision Ownership

The requester explicitly separated the naming cutover from the later file feature on
2026-09-16. The Agent selected the transport-versus-product naming boundary and
hard-cutover mechanics as local technical decisions required to implement that
scope.
