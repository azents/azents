---
title: "Runtime Application Policy Ownership Requirements"
created: 2026-10-07
implemented: 2026-10-07
tags: [runtime, security, gateway]
document_role: primary
document_type: requirements
snapshot_id: proxy-261007
---

# Runtime Application Policy Ownership Requirements

- Snapshot: `proxy-261007`
- Reference: `proxy-261007/REQ`

## Problem

Temporary development applications can have valid form submissions rejected by
platform request-origin policy. Platform-imposed response policies also change
application behavior independently of the application owner.

## Primary Context

### Primary Actor

A user explicitly enabling a temporary Runtime development service.

### Primary Scenario

The user opens the enabled service, submits an ordinary application form, and
receives the application's result without a platform-origin-policy rejection.

## Supporting Scenarios or Effects

- Authenticated programmatic requests work without browser-specific origin signals.
- Application-owned CORS and response policies retain their intended semantics.

## Goals

- Separate platform access control from application request and response policy.
- Preserve authenticated development-service behavior across HTTP methods.

## Non-Goals

- Anonymous service access or a new authentication mode.
- Changing platform login, service activation, exposure lifetime, or permissions.
- Changing transport capacity, Service Worker isolation, or application cookie
  forwarding.
- Deployment or automatic merge.

## Requirements

### REQ-1. Applications own request-origin policy

Application requests must not be rejected by the platform solely because their
Origin or browser Fetch Metadata is absent, opaque, or external.

**Acceptance criteria**

- Authenticated form POST with `Origin: null` reaches the application.
- Authenticated POST, PUT, PATCH, DELETE, and OPTIONS work without Origin.
- Application-defined rejection responses remain authoritative.

### REQ-2. Applications own response policy

The platform must preserve application CORS, cache, referrer, opener, permission,
and framing policy instead of unconditionally imposing its own.

**Acceptance criteria**

- Application policy headers are preserved without duplicate platform overrides.
- Authenticated OPTIONS receives the application response rather than synthesized
  platform CORS permission.

### REQ-3. Platform access protection remains intact

Existing identity, service access, exposure, and Runtime authority checks remain
required independently of application policy.

**Acceptance criteria**

- Requests without platform identity cannot reach application traffic.
- Revoked access and Off/expired services retain their current failure behavior.
- Platform credentials do not enter application traffic.
- Platform authentication and activation retain their own origin protections.

## Fixed Constraints

- No public API, persisted state, migration, configuration mode, or fallback.
- Existing transport and resource bounds remain unchanged.

## Open Assumptions

Browser cross-origin preflights do not carry identity cookies. Supporting them
anonymously is outside this snapshot; application transparency does not imply
anonymous preflight or cross-origin browser access.

## Confirmation

The requester confirmed the platform/application responsibility boundary and
explicitly authorized implementation on 2026-10-07. This document records that
already-approved scope rather than introducing an additional decision.
