---
title: "Runtime Web Application Framing Compatibility Design"
created: 2026-09-15
tags: [runtime, web, security, compatibility, testing]
document_role: primary
document_type: design
snapshot_id: framing-260915
---

# Runtime Web Application Framing Compatibility Design

- Snapshot: `framing-260915`
- Requirements: [framing-260915/REQ](../requirements/framing-260915-runtime-web-application.md)
- Decisions: [framing-260915/ADR](../adr/framing-260915-runtime-web-application.md)
- Document reference: `framing-260915/DESIGN`

## Current Behavior and Gap

`normalize_response_headers()` preserves allowed upstream response fields and then
adds Gateway-owned browser policy fields. Its unconditional
`X-Frame-Options: DENY` applies to proxied application documents, so a same-origin
Storybook manager cannot render its preview iframe. Gateway-generated documents use
separate server response helpers and must retain their framing protection.

## Implementation

Remove the Gateway-added `X-Frame-Options` pair only from proxied application
response normalization. Do not add `X-Frame-Options` to the forbidden-response set:
an application-provided value must continue through normalization unchanged.

Keep Gateway-generated security response helpers unchanged. Keep the remaining
response policy, CORS replacement, reserved-cookie stripping, redirect rewriting,
request normalization, and transport handling unchanged.

Update the Runtime control Living Spec to state the split policy explicitly:
platform-generated documents deny framing, while proxied content follows the
application's own framing headers.

## Test Strategy

- Policy unit coverage asserts that a response without upstream framing policy does
  not gain one and that an application-provided value is preserved.
- Existing Gateway server coverage continues to assert strict Content Security
  Policy on Gateway-generated transfer documents.
- The real Runtime Web browser E2E records the proxied response header and asserts
  that no Gateway-added `X-Frame-Options` is present in both authentication modes.
- Existing Runtime Web HTTP, SSE, WebSocket, credential, origin, CORS, redirect,
  cookie, authority, and hard-limit journeys remain unchanged and run in required
  CI. No new fixture, credential, or live external prerequisite is needed.
- A missing optional browser binary does not weaken the policy unit assertion; the
  required browser lane must still pass where the Runtime Web E2E is scheduled.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Proxied responses receive no Gateway-invented framing header | REQ-1, ADR-D1 | `required` |
| M2 | Application-provided framing headers pass through | REQ-1, ADR-D1 | `required` |
| M3 | Gateway-generated documents retain framing protection | REQ-2, ADR-D1 | `required` |
| M4 | Other Gateway security and transport controls remain unchanged | REQ-3, ADR-D2 | `required` |
| M5 | Policy unit and real-browser regression evidence | REQ-1, REQ-2, REQ-3 | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Gateway-added `X-Frame-Options: DENY` on every proxied application response | REQ-1, ADR-D1 | Application-provided framing policy | `normalize_response_headers()` and its assertions | Policy unit test and real-browser E2E response-header assertion |
| Platform document framing protection | None | REQ-2, ADR-D1 | No change | Existing strict document CSP test and unchanged response helpers |
| Origin, CORS, credentials, cookies, redirects, Service Worker, no-store, and transport bounds | None | REQ-3, ADR-D2 | No change | Existing focused and required regression suites |

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-09-15`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5`
- Approved scope: Remove the Gateway-invented blanket iframe denial from proxied
  application responses, retain platform-document framing protection and all
  independent Runtime Web boundaries, and publish the correction immediately after
  focused verification.
