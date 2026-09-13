---
title: "Runtime Web Browser and Services Correction Decisions"
created: 2026-09-13
tags: [runtime, web, security, frontend, architecture]
document_role: primary
document_type: adr
snapshot_id: runtimeweb-260913
---

# Runtime Web Browser and Services Correction Decisions

- Snapshot: `runtimeweb-260913`
- Requirements: [runtimeweb-260913/REQ](../requirements/runtimeweb-260913-browser-services-correction.md)
- Document reference: `runtimeweb-260913/ADR`

## Decision Summary

- `runtimeweb-260913/ADR-D1` — Browser identity is vendor- and version-neutral.
- `runtimeweb-260913/ADR-D2` — Raw request-cookie cardinality is checked before
  opaque identity validation.
- `runtimeweb-260913/ADR-D3` — Browser-profile persistence and configuration are
  removed as one release boundary.
- `runtimeweb-260913/ADR-D4` — The existing Services view is restored through the
  unified Session supporting-panel navigation.
- `runtimeweb-260913/ADR-D5` — Services reports exposure authority and Runtime
  evidence without background application-port probing.

## Context

The implemented Runtime Web Gateway already treats the Runtime application as an
untrusted origin, strips platform cookies before proxying, validates opaque
identity secrets against current authentication Session and user state, and
revalidates Session access plus exposure authority during long-lived streams.

It also already parses every raw Cookie header and rejects more than one exact
identity-cookie name. A later browser-profile mechanism added an exact Chromium
version and protected-client-hint gate. That gate changed user-visible browser
compatibility without product authority and obscured the simpler existing identity
boundary.

The Services management component, API, localized copy, and state mutations also
already exist. The unified Chat supporting-panel navigation omits the Services
destination and hides the component's internal tab list, making the approved
surface unreachable.

## runtimeweb-260913/ADR-D1. Use browser-neutral opaque identity authentication

**Authority:** `runtimeweb-260913/REQ-1`, `REQ-2`, `REQ-6`;
`web-260912/REQ-3`, `REQ-9`, `REQ-10`, `REQ-11`.

Gateway authentication uses the existing high-entropy opaque identity secret and
server-side authority. Browser vendor, browser version, User-Agent Client Hint, and
browser-profile state are not authentication inputs.

The Gateway retains:

- exact service/broker Host parsing;
- safe-navigation redirect versus programmatic `401`;
- exact Main Web Origin checks for authentication mutations;
- broker binding and one-time ticket exchange in separate-domain mode;
- identity revocation and expiry;
- authentication Session and user-access validation;
- current Session permission and exposure-cycle validation;
- CORS, Fetch Metadata, Service Worker, size, admission, and stream bounds; and
- complete removal of platform Cookie fields before upstream forwarding.

**Rejected alternatives**

- Keep Chromium as the only supported profile: unauthorized product restriction.
- Accept User-Agent-only browser exceptions: forgeable signal that retains the
  wrong browser-gating model.
- Replace the opaque identity with a new stateless token format: unnecessary state
  and migration when the current server-validated secret already provides
  unforgeability and immediate revocation.

## runtimeweb-260913/ADR-D2. Reject ambiguous identity-cookie requests

**Authority:** `runtimeweb-260913/REQ-2`; `web-260912/REQ-10`.

The Gateway reads all raw Cookie header fields and all cookie-pairs in the current
request. It counts exact matches for the configured identity-cookie name:

- zero matches means unauthenticated;
- one match is validated as the opaque identity secret;
- more than one match is a malformed ambiguous request and fails before authority
  lookup or proxy admission.

The check is request-local, content-free in logs, bounded by the existing header
limit, and independent across parallel requests. It does not store request history,
coordinate through Redis, or choose a first/last value.

Broker-binding cookies use the same exact-cardinality rule. The removed
browser-proof cookie has no replacement.

## runtimeweb-260913/ADR-D3. Remove browser-profile state in one release

**Authority:** `runtimeweb-260913/REQ-1`, `REQ-6`, ADR-D1.

Browser-profile fields are removed from identity models, repository methods,
service contracts, Public API schemas, generated clients, Gateway settings,
security fingerprints, Helm values, Main Web probe routes, and E2E fixtures.

A new forward migration drops the identity `browser_profile` column. The release
changes the Runtime Web security fingerprint, so Gateway configuration
synchronization revokes existing identities and discards pending broker bindings
and tickets. Users authenticate again after rollout. Mixed old/new Gateway and API
processes are not a supported steady state.

## runtimeweb-260913/ADR-D4. Restore Services through unified Session navigation

**Authority:** `runtimeweb-260913/REQ-3`, `REQ-4`, `REQ-5`;
`web-260912/REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-12`.

The existing RuntimeServicesPanel and generated-client-backed tRPC mutations remain
the management surface. `services` becomes a first-class unified Session panel
destination, including URL parsing/restoration, desktop navigation, mobile
navigation, selected-state mapping, and visible polling.

No duplicate Services page, alternate state store, or separate management API is
introduced. Chat cards, endpoint confirmation, Agent tools, and Services continue
to fetch the same current projection and use revision-fenced mutations.

Confirmation UI closes only after mutation success. A failed mutation retains the
dialog and its exact request or prepared-service context.

## runtimeweb-260913/ADR-D5. Report only known reachability evidence

**Authority:** `runtimeweb-260913/REQ-5`; `web-260912/REQ-7`, `REQ-12`.

Services distinguishes exposure authority from current Runtime connection evidence.
It does not label Runtime absence as proven application-port failure and does not
probe arbitrary application HTTP paths in the background.

The endpoint surface remains authoritative for application request failures such as
an unavailable port. Services may report that the Runtime is unavailable or that
application reachability has not been checked, while preserving the active
approval and its deadline.

**Rejected alternative**

- Periodically issue HTTP requests to every exposed application: may trigger
  application side effects, invent health semantics, and create unbounded traffic.

## Consequences

- Existing users must establish a new Runtime Web identity once after rollout.
- Browser compatibility no longer changes with a chart-level Chromium range.
- The product relies on server-issued opaque identity validation and explicit
  duplicate rejection rather than browser-vendor enforcement.
- Services becomes visible without duplicating the existing management
  implementation.
- Runtime status copy becomes more precise while application-level failures remain
  visible at the endpoint that observed them.
