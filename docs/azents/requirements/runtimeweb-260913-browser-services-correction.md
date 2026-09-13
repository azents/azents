---
title: "Runtime Web Browser and Services Correction Requirements"
created: 2026-09-13
updated: 2026-09-13
tags: [runtime, web, security, frontend]
document_role: primary
document_type: requirements
snapshot_id: runtimeweb-260913
---

# Runtime Web Browser and Services Correction Requirements

- Snapshot: `runtimeweb-260913`
- Document reference: `runtimeweb-260913/REQ`

## Problem

Runtime Web currently rejects users according to a browser vendor and exact-version
policy that was not approved as product scope. The already-approved Services
management surface also exists in implementation but is disconnected from the
actual Session supporting-panel navigation, so users cannot reach it through the
product.

## Primary Context

### Primary Actor

A user with access to an Agent Session who needs to expose, inspect, approve, and
close temporary Runtime Web services from the Main Web in their ordinary browser.

### Primary Scenario

1. The user opens the Session supporting panel and selects Services on desktop or
   mobile.
2. The user creates or manages a service using the current Session-and-port
   projection.
3. The same stable address and request/cycle state remain visible across Chat,
   Services, and endpoint confirmation.
4. The user opens an approved service without being rejected because of browser
   vendor, version, or client-hint availability.
5. The Gateway authenticates only an unambiguous server-issued identity and
   continues to enforce current Session access, exposure approval, expiration, and
   origin boundaries.

## Supporting Scenarios or Effects

- Existing Chat cards and endpoint confirmation continue to operate on the same
  current service projection.
- A user can distinguish active exposure authority from temporary Runtime
  unavailability without implying that exposure management starts or stops the
  application.
- Invalid, missing, duplicated, expired, or revoked identities fail closed in every
  supported browser.

## Goals

- Remove the unapproved browser-vendor and exact-version product restriction.
- Restore the approved Services management entry point in the unified Session UI.
- Preserve the existing Runtime Web credential, permission, approval, and
  revocation boundaries.
- Remove obsolete browser-profile state, configuration, and verification surfaces.

## Non-Goals

- Adding a third authentication mode or a per-service authentication choice.
- Treating exposure management as Runtime process management.
- Background HTTP health checks against arbitrary application ports.
- Weakening Session authorization, exposure approval, expiration, origin, CORS,
  Service Worker, traffic-bound, or credential-stripping policy.
- Selecting one value from an ambiguous duplicate identity-cookie request.

## Requirements

### REQ-1. Browser-neutral authenticated access

Runtime Web authentication and application access must not depend on a browser
vendor, exact browser version, User-Agent Client Hint, or a code-owned browser
allowlist.

**Acceptance criteria**

- Chromium, Firefox, and WebKit requests follow the same identity and authorization
  contract.
- Missing or different browser-version signals do not produce an upgrade-required
  response.
- Safe unauthenticated navigation enters the trusted Main Web authentication flow;
  unauthenticated programmatic traffic receives the normal authentication failure.
- Browser compatibility is not configurable as an installation-specific vendor or
  version restriction.

### REQ-2. Unambiguous server-issued identity

The Gateway must authenticate only one exact server-issued identity value from the
current request.

**Acceptance criteria**

- No matching identity cookie is treated as unauthenticated.
- Exactly one matching identity cookie is validated through the existing opaque
  secret, revocation, expiry, authentication Session, user, mode, and current
  authority checks.
- More than one matching identity cookie in one Cookie field or across multiple
  Cookie fields is rejected without selecting a value.
- Duplicate detection is request-local and does not retain request history or
  require Redis.
- Platform cookies and identity material never reach the Runtime application.

### REQ-3. Reachable Services management surface

The existing Services surface must be reachable through the Session supporting
panel and its URL-restorable navigation on desktop and mobile.

**Acceptance criteria**

- Services appears alongside the other Session supporting-panel destinations.
- Selecting Services renders the existing current-projection management surface.
- A `services` panel URL restores the same destination after navigation or reload.
- Services remains available while the Runtime is absent or unavailable.
- Automatic refresh runs while Services is the visible supporting-panel
  destination.

### REQ-4. Complete service management behavior

The Services surface must provide the previously approved current-state management
actions without relying on an Agent request card.

**Acceptance criteria**

- Users can directly create a finite exposure after reviewing the stable address,
  duration, and untrusted-application warning.
- Users can approve, reject, or cancel the exact current pending request.
- Users can request exposure again without extending the current active cycle.
- Users can close the exact active cycle without stopping the application process.
- Stable URL display, copy, and open actions are available when installation
  configuration permits a URL.
- Active exposure and a simultaneous pending request are shown independently.

### REQ-5. Honest state and recoverable interaction

Services UI state must describe the authority and Runtime evidence it actually
knows and preserve user context when a mutation fails.

**Acceptance criteria**

- Pending, active, active with pending request, expired, closed, inactive, and
  installation-unconfigured states remain distinct.
- Runtime unavailability is not labeled as proven application-port failure.
- Create and approval confirmation dialogs remain open when their mutation fails.
- Mutation success refreshes the current service projection before dismissing the
  corresponding confirmation state.
- Controls remain usable and understandable on narrow mobile layouts.

### REQ-6. Removal and regression evidence

The obsolete browser restriction and disconnected-navigation failure must not remain
in code, persisted schema, deployment configuration, current Specs, or tests.

**Acceptance criteria**

- Browser profile, Chromium range, client-hint admission, browser capability probe,
  and browser-proof cookie paths are absent from active product contracts.
- Existing identity, broker, approval, CORS, Runtime transport, and stream
  revocation regression suites remain green.
- Tests cover duplicate identity cookies, browser-neutral authentication, Services
  navigation restoration, direct creation, request decisions, rerequest, close, and
  mobile access.

## Fixed Constraints

- `web-260912/REQ-1` through `REQ-13` remain authoritative except where an
  unapproved browser restriction previously narrowed their product scope.
- Existing Session permission and finite approval-cycle authority remain unchanged.
- The Runtime application remains an untrusted origin.
- Existing generated-client, migration, localization, logging, and Redis-optional
  conventions apply.
- Historical implemented snapshots remain unchanged; current behavior is corrected
  through this new snapshot and Living Specs.

## Open Assumptions

- Runtime connection evidence can distinguish Runtime availability without probing
  arbitrary application HTTP paths.

## Confirmation

Confirmed by the requester on 2026-09-13. The requester explicitly rejected the
unapproved Chromium-only product restriction, approved request-local duplicate
identity-cookie rejection with existing server-issued identity validation, and
directed implementation of the previously confirmed Services management surface.
