---
title: "Runtime Application Policy Ownership Design"
created: 2026-10-07
implemented: 2026-10-07
tags: [runtime, security, gateway]
document_role: primary
document_type: design
snapshot_id: proxy-261007
---

# Runtime Application Policy Ownership Design

- Requirements: [proxy-261007/REQ](../requirements/proxy-261007-runtime-application-policy.md)
- Decision: [proxy-261007/ADR-D1](../adr/proxy-261007-runtime-application-policy.md)

## Current Behavior and Gap

The Gateway currently authorizes browser Origin/Fetch Metadata, synthesizes
same-Agent CORS preflight, removes application access-control headers, and adds
`no-referrer`, `no-store`, opener, and permission policies. This can cause a
same-origin HTML form POST to carry `Origin: null` and then be rejected.

## Design Authority

- Design revision: `1`

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Forward authenticated application HTTP/WebSocket requests without application-origin admission | REQ-1, ADR-D1 | required |
| M2 | Preserve app policy headers and proxy authenticated OPTIONS | REQ-2, ADR-D1 | required |
| M3 | Retain platform identity/access/exposure, broker protections, credential isolation, transport bounds, and Service Worker isolation | REQ-3, fixed constraints, existing Runtime Control Spec | existing |
| M4 | Retain loopback Host/Origin/Referer/redirect/cookie adaptation without origin-based denial | M1, M3, existing Runtime Control Spec | derived |

## Architecture and Ownership

Service resolution and exact identity extraction precede normal authority
admission for all application methods, including OPTIONS. Remove the independent
application-origin gate and local preflight handler. The existing stream bridge,
Control admission, Runner loopback client, and access-revalidation guard are reused.

Application response normalization removes only existing transport and reserved
credential fields and performs existing local cookie/redirect rewriting.
Application CORS, cache, referrer, opener, permissions, and framing headers pass
through. Platform-owned broker/authentication/error responses retain security
headers and exact-origin checks.

The same-service Origin/Referer rewrite remains because the Runner connects to a
loopback Host. Null, opaque, malformed, or external application values are retained
instead of being used as a platform admission predicate.

## State, Interfaces, and Operations

No public API, database, protocol, migration, new mode, or configuration changes.
Deploying the updated Gateway changes application policy behavior. Identity and
service lifecycle remain durable platform authority. Existing status/error
contracts and content-free logging remain; no application paths/headers are logged.
Rollback uses the prior Gateway build without data migration or replay.

## Removal and Replacement

| Obsolete behavior | Removal authority | Replacement | Boundary | Absence evidence |
| --- | --- | --- | --- | --- |
| Origin/Fetch Metadata admission and CORS allowlists | M1, M2 | Authenticated application forwarding | Gateway endpoint | No origin evaluator/allowlist calls |
| Synthesized preflight and CORS decision data | M2 | Normal authenticated OPTIONS transport | Gateway endpoint/adapters | No CORS decision arguments |
| Same-Agent source-origin authority lookup | M1 | Existing target-service access authority | Service/repository | No lookup or dead interface |
| Forced app policy response headers | M2 | Upstream application policy | Response normalization | Header preservation tests |
| Tests asserting removed policy | M1, M2 | Method/origin and OPTIONS regressions | Narrow tests and browser E2E | Focused and required CI |

No persisted state, generated public clients, or configuration becomes obsolete.

## Test Strategy

- Primary E2E: extend the existing real Runtime/TLS/browser Gateway relay journey
  with a native HTML form POST under application `no-referrer` policy. It must
  reach the Runtime application with `Origin: null` and return the form result.
- Narrow matrix: authenticated POST/PUT/PATCH/DELETE/OPTIONS across missing, null,
  external, and same-service origins; custom request headers; upstream response
  policy preservation; missing identity and broker-origin rejection.
- Existing fixtures create all product state via public/admin APIs. No new
  fixture seed or credential preparation is required.
- Required CI runs the folder-owned Web E2E lane and backend quality checks.
  JUnit, pytest output, and failure diagnostics are evidence; no live/external
  credentialed tests are introduced.
- Missing local Docker/image/browser readiness blocks local E2E evidence, not
  product success. Required CI must pass before delivery is declared complete.

## Authority and Feasibility

Every mechanism maps to the requester-approved ownership change or retained
platform behavior. Gateway/Runner transport already carries arbitrary HTTP
methods/headers. Focused HTTP adapter tests verify null-origin form-compatible
traffic and preservation of identity isolation. No new authority or interface
is needed; anonymous browser preflight remains explicitly outside scope.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-10-07`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: the explicitly authorized transparent application-policy
  boundary with retained platform authentication/access and required local
  transport adaptation. This records the approved implementation direction;
  no additional mode or anonymous-access decision is claimed.
