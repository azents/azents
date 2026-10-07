---
title: "Runtime Application Header Forwarding Design"
created: 2026-10-07
implemented: 2026-10-07
tags: [runtime, gateway, security]
document_role: primary
document_type: design
snapshot_id: headers-261007
---

# Runtime Application Header Forwarding Design

Requirements: [headers-261007/REQ](../requirements/headers-261007-runtime-application-forwarding.md)
Decision: [headers-261007/ADR-D1](../adr/headers-261007-runtime-application-forwarding.md)

## Design Authority

- Revision: `1`

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Ordered end-to-end header forwarding and exact platform-cookie separation | REQ-1, REQ-2, ADR-D1 | required |
| M2 | Protocol-aware hop/Connection/handshake consumption | REQ-2, ADR-D1 | required |
| M3 | Propagate application headers on WebSocket 101 | REQ-1 | required |
| M4 | Retain identity/access/exposure/generation, limits and local routing adaptation | REQ-2, fixed constraints, Runtime Control Spec | existing |

## Architecture and Interfaces

Gateway normalization separates platform cookie pairs from each Cookie header
without converting application cookies into a map. Repeated application cookie
names and raw values remain ordered. Reserved response Set-Cookie uses the same
exact platform-name set. Unrelated lookalike names remain application-owned.

Gather Connection tokens across all repeated fields and consume nominated names.
HTTP forwarding consumes hop fields and regenerates local Host while retaining
all other fields, including Origin/Referer and WebSocket-named application fields.
WebSocket forwarding additionally consumes the handshake fields generated anew
by the existing Runner and Gateway adapters. Sec-WebSocket-Protocol remains
validated and negotiated by those adapters. Success responses include normalized
app fields before the browser-side handshake is prepared.

Control already relays ordered typed header tuples and Runner uses a raw HTTP
client and wsproto handshake; no new authority, mode, or compatibility interface
is needed. No data migration or new logging labels. Never log cookie/header values.
Rollback restores the previous build without affecting durable identity/exposure.

## Removal and Replacement

| Existing behavior | Authority | Replacement | Evidence |
| --- | --- | --- | --- |
| Entire Cookie removal and broad prefix reservation | M1 | Exact platform-cookie filtering | Duplicate-cookie/credential isolation tests |
| Origin/Referer rewriting | M1 | Raw application values | Header preservation tests |
| Protocol-independent handshake blacklist | M2 | Protocol-aware transport consumption | HTTP/WS header matrix |
| Missing Connection-token removal | M2 | Full repeated Connection nomination handling | Mixed-case dynamic hop tests |
| Missing 101 app headers | M3 | Normalized app headers on upgrade | App cookie/header handshake tests |

No persisted state, configuration, or generated clients become obsolete.

## Test Strategy

Extend the existing real Runtime/TLS/browser relay E2E with a disposable app login
cookie round-trip, application-header echo, platform-cookie absence, and preserved
Origin/Referer. Existing public/admin fixture paths provide product state and no
new live credential snapshot is required. Narrow tests cover repeated Cookie and
Set-Cookie values, reserved/lookalike names, dynamic hop fields, and HTTP versus
WebSocket handshakes. Required Web/required E2E and backend CI provide JUnit/output
evidence; local failures must be reported rather than counted as passing.

## Authority and Feasibility

Every changed behavior is directly required by the requester's clarified header
ownership rule. Existing ordered protobuf headers and raw Runner client preserve
application values. Platform identity extraction remains before app filtering;
access guards and bounds are unchanged. Browser-provided identity must still be
present; anonymous CORS preflight remains outside scope.

## Design Approval

- Mode: Collaborative
- Owner: requester
- Date: 2026-10-07
- Approved revision: 1
- Authority IDs: M1, M2, M3, M4
- Scope: explicitly authorized forwarding of all application headers with only
  proxy-consumed transport/authentication fields excluded. No additional
  authentication or deployment authority is claimed.
