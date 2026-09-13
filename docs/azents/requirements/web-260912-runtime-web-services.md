---
title: "Temporary Runtime Web Services Requirements"
created: 2026-09-12
tags: [runtime, web, security, frontend, backend]
document_role: primary
document_type: requirements
snapshot_id: web-260912
---

# Temporary Runtime Web Services Requirements

- Snapshot: `web-260912`
- Document reference: `web-260912/REQ`

## Problem

A user cannot directly use a web application prepared by an Agent inside its
Runtime merely by receiving the application's loopback address. Publishing it
outside the normal Azents access boundary would require separate infrastructure
work and could disclose application access or platform credentials. Users need
temporary, authenticated use of these applications without a permanent hosting
product or coupling exposure approval to the lifetime of a Runtime instance.

## Primary Context

### Primary Actor

A user with access to a Session who wants to use a temporary web application
prepared by its Agent.

### Primary Scenario

1. The Agent obtains the actual address associated with the Session and an
   application port before requesting exposure and uses it in application setup.
2. The Agent prepares the application using ordinary Runtime capabilities and
   requests its exposure.
3. The request immediately returns the address and pending state. The Agent
   continues working without waiting for a person. The address presents an
   Azents approval surface rather than the unapproved application.
4. An authorized user later approves the request from its Chat item, the Services
   view, or the endpoint's approval surface.
5. The user accesses the application at that same address, including ordinary HTTP
   requests involving other approved services.
6. The exposure expires or an authorized user or Agent closes it. When needed,
   another request and user approval establish a new finite exposure at the same
   address without managing the application's process lifetime.

## Supporting Scenarios or Effects

- A user creates and manages an exposure directly without an Agent request.
- A new request may remain pending while the previous exposure is still active.
- Runtime restart, replacement, and temporary unavailability do not revoke an
  exposure approval or extend its expiration.
- Administrators configure one supported authentication mode per installation.

## Goals

- Enable actual use of temporary dashboards and web tools as well as previews.
- Preserve current Session access rules and protect platform credentials.
- Make approval, expiration, and application reachability independently visible.
- Provide repeatable addresses without automatic or unlimited active serving.

## Non-Goals

- Permanent hosting or an indefinitely active approval.
- A separate frontend/backend service classification or dependency-approval model.
- Separate private-versus-Session service sharing permissions.
- Process start, stop, or restart as a side effect of exposure management.
- A distinct extension capability instead of a fresh request and user approval.
- Per-service authentication-mode selection or automatic fallback between modes.
- A guarantee of uninterrupted connections across Runtime or authentication-mode
  changes, or replay of failed application mutations.

## Requirements

### REQ-1. Stable Session-and-port addresses

The actual service address must be deterministically associated with the Session
and port and available before exposure is requested.

**Acceptance criteria**

- Repeated address lookups for the same Session and port return the same address
  while the installation's service-address configuration remains unchanged.
- Cancellation, rejection, expiration, closure, and Runtime replacement do not
  require a different address for a subsequent request at that Session and port.
- Address lookup does not grant approval, submit a request, or start a Runtime.
- An address is not reassigned to a different Session or port and is not itself an
  access credential.
- Address preparation has no reservation-expiration deadline.

### REQ-2. Nonblocking Agent requests and explicit user approval

Every Agent exposure request requires user approval, but the Agent must not wait
for it to complete.

**Acceptance criteria**

- The request returns a service address and pending status before user approval.
- The Agent can perform its next action while approval is pending.
- Before approval the endpoint presents the platform's approval surface rather
  than proxying the internal application.
- Visiting an address, authenticating, or repeating an Agent request does not
  implicitly approve exposure.
- Approval may occur later through the Chat item, Services view, or endpoint
  approval surface, and all these places reflect the same request result.

### REQ-3. Existing Session permissions

Approval, access, and management follow existing Session access permission, not a
new service-sharing permission model.

**Acceptance criteria**

- A user with Session access can approve and manage its services; a user without
  that access cannot approve, access, or manage them.
- One authorized user's approval activates the exposure for the Session, while
  each accessing user still supplies their own valid authentication.
- There is no additional per-user exposure approval or private/sharing selector.
- Knowing an address does not bypass current Session authorization.

### REQ-4. Direct user management and Agent closure

Users can create services directly. The Agent can close both Agent-requested and
user-created services in its current Session.

**Acceptance criteria**

- Direct creation includes an explicit user confirmation of exposure.
- The Agent's closing authority is not limited to cancellation of its own pending
  requests or to services it created.
- Closing a service blocks new application access and terminates active
  long-lived exposure connections without terminating the Runtime application.
- Authority is not extended to another Session by specifying its identifier.

### REQ-5. Indefinite pending requests and finite active exposure

Pending approval has no elapsed-time expiration. Each approved exposure has a
finite deadline independent of traffic and Runtime availability.

**Acceptance criteria**

- A valid pending request does not expire merely because time has passed.
- The approval action presents the active duration and establishes its expiration.
- Requests, traffic, heartbeats, and Runtime recovery do not automatically extend
  the approved deadline.
- At expiration, new application access is denied and existing long-lived
  exposure connections are terminated.
- Address identity and application processes survive exposure expiration.
- Pending indefinitely does not mean bypassing Session validity, explicit
  cancellation, or bounded admission of distinct requests.

### REQ-6. Request again instead of extend

A fresh request and user approval reuse the deterministic address and establish a
new exposure period. There is no separate extension operation.

**Acceptance criteria**

- Submitting another request during active exposure leaves the current application
  accessible until its existing expiration and does not modify that expiration.
- The endpoint is not replaced by an approval page merely because a new request
  is pending while the current approval remains active.
- Approving the new request starts a new validity period at that approval time.
- If the current period expires first, application access stops while the pending
  request remains available for approval.
- Repeated requests cannot create automatic perpetual active service.

### REQ-7. Runtime-independent approval and lifetime

Logical exposure state must be independent of the Runtime instance and Runner
connection lifecycle.

**Acceptance criteria**

- Runtime stop, restart, replacement, or Runner reconnection does not cancel
  pending requests or revoke otherwise-valid approved exposure.
- While unreachable, the service reports unavailability separately from approval
  and retains its original expiration.
- After recovery and before expiration, the same address can reach the current
  authorized Agent Runtime and port without a new exposure approval.
- An obsolete connection cannot be reused to reach an unrelated Runtime, Agent,
  Session, or port.
- Exposure management does not become process management or pause Runtime
  lifecycle operations until browser cleanup completes.

### REQ-8. One HTTP service model

Services use the same HTTP exposure behavior without frontend/backend roles.

**Acceptance criteria**

- Ordinary page, asset, API, streamed HTTP, server-sent event, and WebSocket
  development-tool interactions are supported within the declared limits.
- Calls involving another service apply that target's current authorization,
  approval, and expiration rather than automatically approving dependencies.
- Application setup can use the previously obtained real addresses without
  embedding Azents authentication secrets in application code.
- API requests do not receive an unapproved internal application response, and
  authentication/approval failures are distinguishable from successful app data.
- The implementation does not invent frontend/backend resource types to make
  browser authentication work.

### REQ-9. Two installation authentication modes

Support shared-cookie authentication and separate-domain authentication transfer,
with exactly one explicitly selected mode per installation. Separate-domain mode
is the recommended default.

**Acceptance criteria**

- Both modes reuse the existing user's Azents authentication and apply the same
  Session permissions, exposure approval, and expiration semantics.
- Services and Agents cannot select a different mode from their installation.
- Authentication failure in one mode does not automatically try the other.
- Shared-cookie mode does not distribute the long-lived refresh credential to
  the service Gateway or Runtime applications.
- Mode switching is explicit and need not be zero-downtime; stale credentials do
  not remain accepted simply because the previous mode once trusted them.

### REQ-10. Untrusted-application and credential boundary

An exposed Runtime application must not gain platform control or authentication
credentials through exposure, including when the same service address is reused.

**Acceptance criteria**

- Azents bearer/refresh tokens, authentication-transfer tickets, and Gateway
  grants are absent from service URLs, Runtime requests, and application code.
- The application's origin is distinct from the main platform application's
  origin.
- Unapproved application content cannot impersonate the authoritative approval
  action or authorize itself.
- Reused-origin browser state cannot bypass the platform's current approval and
  authorization checks.
- Caller-controlled headers, targets, redirects, or stale Runtime messages cannot
  expand authorized access to another Session, Runtime, port, or internal service.
- User-facing language explains that authenticated access does not certify the
  application's content, downloads, or requests for sensitive information.

### REQ-11. Bounded traffic and current authority

Temporary application use must not create unbounded memory, connection, or
control-plane resource consumption or retain access after authority is lost.

**Acceptance criteria**

- Malformed, excessive, slow, and stale requests fail within declared bounds and
  do not prevent unrelated Chat and Runtime control work from progressing.
- Long-lived connections revalidate current user access and approved exposure;
  revoked access does not remain active indefinitely.
- Known expiration is enforced without a traffic-based extension.
- Losing expendable connection coordination fails uncertain connections closed;
  new correctly authorized connections can recover without restoring Redis data.
- Redis is not a correctness, persistence, or high-availability prerequisite.

### REQ-12. Coherent feedback and recovery

Chat, Services, and endpoint surfaces distinguish approval from reachability.

**Acceptance criteria**

- Users can distinguish pending approval, active exposure, pending rerequest,
  expired/closed exposure, authentication needed, permission denied, application
  unavailable, Runtime unavailable, capacity limits, and installation not ready.
- Runtime unavailability is not described as approval cancellation or a need for
  a replacement address.
- Desktop and mobile provide the same approval, state, cancellation, and closure
  semantics with accessible action labels and focus behavior.
- Missing installation configuration is explicit rather than silently bypassed
  using an unauthenticated or main-application-origin proxy.

### REQ-13. Content-free observability and reproducible validation

Operational evidence must support debugging without collecting application or
credential content.

**Acceptance criteria**

- Audit and diagnostics identify bounded lifecycle outcomes and authorization
  failures without request/response bodies, credentials, full paths, or queries.
- Tests demonstrate both authentication modes, nonblocking requests, indefinite
  pending state, finite exposure, rerequest transitions, and Runtime-independent
  approval with actual Runtime and browser/API evidence.
- Security regression evidence covers credential isolation, stale or forged
  authority, request normalization, and approval integrity at reused addresses.

## Fixed Constraints

- Existing Session and Agent ownership rules remain authoritative.
- Runtime is an untrusted execution boundary; current transport identity must be
  checked without coupling approval lifetime to that transport.
- Runtime application content is not a trusted platform UI.
- Existing repository layering, generated-client, migration, logging, localization,
  and Redis-optional conventions apply.
- Historical technical proposals are not automatically approved mechanisms.
- Public artifacts must contain no private source-system provenance or user data.

## Open Assumptions

- Two hours is the discussed initial active-duration baseline, not a separately
  requester-specified numeric requirement. The final technical decision must
  name its chosen finite default and tests without attributing that number to
  the requester.
- Authentication-transfer lifetime, revocation-latency bounds, and traffic limits
  are technical baseline choices to record and verify in the ADR and Design.
- A declared browser/protocol support envelope and treatment of browser-side
  offline data must not be confused with removal of already-downloaded content.

## Confirmation

The requester confirmed the product outcomes in this snapshot during the
2026-09-12 design discussion, explicitly directed that settled decisions not be
reopened, and then requested autonomous completion of the remaining technical
design and implementation on 2026-09-12. This snapshot records those confirmed
outcomes without adding a new product approval gate. Remaining material technical
choices are delegated to the autonomous technical decision owner; product-scope
changes are not delegated by that instruction.
