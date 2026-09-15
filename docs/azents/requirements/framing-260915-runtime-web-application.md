---
title: "Runtime Web Application Framing Compatibility Requirements"
created: 2026-09-15
tags: [runtime, web, security, compatibility]
document_role: primary
document_type: requirements
snapshot_id: framing-260915
---

# Runtime Web Application Framing Compatibility Requirements

- Snapshot: `framing-260915`
- Document reference: `framing-260915/REQ`

## Problem

Runtime Web Gateway currently adds a blanket browser framing denial to every
proxied application response. This overrides the exposed application's own browser
policy and prevents ordinary development tools such as Storybook from loading their
same-origin preview document in an iframe. The restriction was not part of the
confirmed product requirements and conflicts with the existing requirement to
support ordinary development-tool interactions.

## Primary Context

### Primary Actor

A user accessing an approved temporary Runtime web application through its stable
service address.

### Primary Scenario

1. The user opens an approved development tool or web application.
2. The application loads its pages, assets, APIs, streams, and same-origin embedded
   documents through the same Runtime Web endpoint.
3. The Gateway preserves platform authorization and transport security boundaries
   without replacing the application's own framing policy.

## Goals

- Restore application-controlled iframe behavior for proxied Runtime content.
- Preserve the trusted platform-document framing boundary.
- Preserve current authorization, credential isolation, origin, redirect, traffic,
  and Service Worker protections.

## Non-Goals

- Allow Runtime application content to render or execute trusted platform approval
  controls.
- Remove application-provided `X-Frame-Options` or Content Security Policy fields.
- Relax Session access, exposure approval, expiration, authentication, CORS, SSRF,
  redirect, cookie, request-size, or stream authority.
- Change the existing initial-release Service Worker and cache policy.

## Requirements

### REQ-1. Application-controlled framing

Proxied application responses must not receive a Gateway-invented blanket framing
denial.

**Acceptance criteria**

- A proxied application response without an application-provided framing policy is
  not given `X-Frame-Options: DENY` by the Gateway.
- Same-origin iframe use such as a Storybook preview can load through the approved
  endpoint when the application itself permits it.
- Application-provided `X-Frame-Options` and Content Security Policy remain intact
  subject to ordinary bounded header validation.

### REQ-2. Trusted platform documents remain protected

Gateway-generated authentication, approval, error, and transfer documents retain
their existing framing protection.

**Acceptance criteria**

- Platform-generated HTML documents remain non-embeddable through their current
  `X-Frame-Options` and document Content Security Policy.
- Removing the application-response override does not move approval or other
  control mutations onto the untrusted service origin.

### REQ-3. Existing security and transport boundaries remain unchanged

The framing correction must not relax independent Runtime Web security or traffic
controls.

**Acceptance criteria**

- Exact Host and Origin authorization, Gateway-owned CORS, platform credential and
  reserved-cookie isolation, SSRF and redirect policy, Service Worker rejection,
  `Cache-Control: no-store`, and current authority revalidation remain enforced.
- Response header normalization continues to preserve ordered application headers,
  remove hop-by-hop and upstream CORS fields, and normalize permitted cookies and
  redirects.
- Existing HTTP, SSE, and WebSocket regression suites remain green.

## Fixed Constraints

- The confirmed `web-260912/REQ-8` development-tool compatibility outcome remains
  authoritative.
- The Runtime application remains untrusted and distinct from the Main Web control
  origin.
- Gateway-generated platform documents and proxied application responses are
  separate policy classes.

## Open Assumptions

None.

## Requester Confirmation

On 2026-09-15, after the Gateway-added framing denial and its Storybook iframe
impact were identified, the requester rejected the unapproved HTTP restriction and
directed correction under the already-confirmed Runtime Web compatibility scope.
