---
title: "Runtime Web Application Framing Compatibility Decisions"
created: 2026-09-15
tags: [runtime, web, security, compatibility, architecture]
document_role: primary
document_type: adr
snapshot_id: framing-260915
---

# Runtime Web Application Framing Compatibility Decisions

- Snapshot: `framing-260915`
- Requirements: [framing-260915/REQ](../requirements/framing-260915-runtime-web-application.md)
- Document reference: `framing-260915/ADR`

## Context

The original Runtime Web Gateway decision applied framing denial to both trusted
Gateway documents and untrusted proxied application responses. That shared policy
was broader than the product authority. It blocks same-origin application iframe
composition, including Storybook's preview document, and therefore conflicts with
`web-260912/REQ-8` and `framing-260915/REQ-1`.

The trusted Gateway document boundary remains necessary because authentication,
approval, and transfer pages are platform-controlled surfaces. Proxied application
content has no such platform authority and must retain control of its own framing
policy while the Gateway continues to enforce independent access and credential
boundaries.

## Decision Summary

- `framing-260915/ADR-D1` — Separate trusted platform-document framing policy
  from proxied application framing policy.
- `framing-260915/ADR-D2` — Preserve independent Gateway security and transport
  controls while removing only the unauthorized application framing override.

## Decisions

### framing-260915/ADR-D1. Applications own their framing policy

**Authority:** `framing-260915/REQ-1`, `REQ-2`, and `web-260912/REQ-8`.

The Gateway does not add `X-Frame-Options` to proxied application responses.
Application-provided `X-Frame-Options` and Content Security Policy headers pass
through the existing bounded response-header normalization and remain authoritative
for application content.

Gateway-generated authentication, approval, bounded-error, and transfer documents
retain their current framing protection, including `X-Frame-Options: DENY` and the
strict document Content Security Policy where applicable.

**Consequences**

- Same-origin iframe composition works when the application permits it.
- Applications remain free to deny or constrain framing with their own headers.
- Platform-controlled documents remain protected against embedding by Runtime
  application content.

**Rejected alternatives**

- Keep blanket `DENY`: directly breaks required development-tool interactions.
- Replace it with Gateway-owned `SAMEORIGIN`: still overrides application policy
  and invents a product compatibility restriction without authority.
- Remove framing protection from all Gateway responses: unnecessarily weakens
  trusted platform documents.

**Required evidence**

- A proxied response without an upstream framing header receives none.
- An upstream application framing header remains present and unmodified.
- Gateway-generated security documents retain their existing framing denial.

### framing-260915/ADR-D2. Preserve independent Gateway boundaries

**Authority:** `framing-260915/REQ-3`, `web-260912/REQ-10`, and
`web-260912/REQ-11`.

The correction changes no authentication, authorization, request normalization,
origin, CORS, credential, cookie, redirect, SSRF, Service Worker, cache, stream, or
traffic-limit rule. Gateway-owned `Cache-Control: no-store`,
`Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`, and the
configured `Permissions-Policy` remain unchanged in this correction because they
are independent of the observed iframe denial. Any later compatibility change to
those policies requires its own authority and evidence rather than being bundled
into this defect correction.

**Consequences**

- The observed Storybook defect is corrected with a narrow policy change.
- Existing credential and authority protections retain their current behavior and
  regression coverage.
- Other browser-policy compatibility questions remain visible instead of being
  silently changed during this correction.

**Rejected alternatives**

- Remove all Gateway-added browser policy headers together: exceeds the confirmed
  defect scope and would combine distinct security and compatibility decisions.
- Add a Storybook-specific path or port exception: couples the Gateway to one tool
  and leaves the unauthorized global policy in place.

**Required evidence**

- Existing policy tests for no-store, CORS replacement, reserved-cookie stripping,
  redirect rewriting, and request normalization remain green.
- Focused and whole-subproject Python quality checks pass.
