---
title: "Runtime Web Browser and Services Correction Design"
created: 2026-09-13
updated: 2026-09-13
tags: [runtime, web, security, frontend, testing]
document_role: primary
document_type: design
snapshot_id: runtimeweb-260913
---

# Runtime Web Browser and Services Correction Design

- Snapshot: `runtimeweb-260913`
- Requirements: [runtimeweb-260913/REQ](../requirements/runtimeweb-260913-browser-services-correction.md)
- Decisions: [runtimeweb-260913/ADR](../adr/runtimeweb-260913-browser-services-correction.md)
- Document reference: `runtimeweb-260913/DESIGN`

## Current Behavior and Gaps

Runtime Web currently has two independent defects.

First, Gateway admission and Main Web identity establishment require an exact
Chromium profile. Browser vendor/version/client-hint checks run before ordinary
unauthenticated handling, so WebKit and Firefox receive `426` instead of entering
the existing identity flow. Browser profile is threaded through settings, Public
API, services, repository projections, the identity table, Helm, generated clients,
and E2E.

Second, RuntimeServicesPanel already implements the approved management operations,
but unified Session panel navigation omits `services`. WorkspacePanel hides its
internal tabs when driven by external navigation, leaving no product entry point.
The container also closes confirmation state before mutation success and labels a
Workspace/Runtime condition as application unavailability.

The Gateway's `_exact_cookie` already provides the approved raw-header duplicate
identity-cookie behavior. It remains the implementation boundary rather than being
replaced.

## Requirements and Decision Traceability

| Requirement | Design mechanism |
| --- | --- |
| REQ-1 | Remove browser-profile gates and use the existing opaque identity flow |
| REQ-2 | Retain `_exact_cookie`; remove the browser-proof cookie |
| REQ-3 | Add `services` to unified Session navigation and visible refresh |
| REQ-4 | Reuse RuntimeServicesPanel and current revision-fenced mutations |
| REQ-5 | Correct Runtime/reachability copy and close dialogs on success |
| REQ-6 | Remove schema/config/API/Web/test surfaces and add cross-browser/navigation regression |

## Browser-Neutral Gateway Processing

Endpoint processing remains:

1. reject malformed Hosts, framing, and Service Worker traffic;
2. resolve the exact endpoint;
3. answer valid same-root CORS preflight locally without identity or Runtime
   transport;
4. read the configured identity cookie through `_exact_cookie`;
5. redirect safe unauthenticated navigation to Main Web authentication, otherwise
   return `401`;
6. validate the opaque secret, authentication Session, user, mode, expiry,
   revocation, Session access, current cycle, Runtime/Runner generation, and
   admission quota;
7. normalize headers and stream through Runtime Control and Runner.

`require_admitted_browser`, exact Chromium version settings, browser profile,
browser-proof HMAC/cookie, and `426 upgrade_required` are removed. Fetch Metadata
and Origin validation remain independent policy inputs and are not removed with the
browser allowlist.

WebSocket requests use the same single identity cookie as HTTP. They no longer
require a browser-proof cookie established by an earlier HTTP response.

## Identity Establishment

Shared-cookie mode:

- Main Web verifies its authenticated user and exact request Origin.
- It calls the Public API shared-identity endpoint without a browser-profile body.
- It writes the returned opaque identity using the configured Secure, HttpOnly,
  SameSite, Domain, and Path policy.

Separate-domain mode:

- Main Web starts the existing initiation and Main-binding exchange.
- Broker binding and one-time POST-body ticket behavior remain unchanged.
- Redeem validates the broker-binding cookie with `_exact_cookie` and creates an
  opaque identity without browser-profile input.

The Main Web capability-probe route and probe cookies are deleted. Main binding
encoding/decoding, exact Origin validation, transient-cookie cleanup, and logout
identity revocation remain.

## Persistence and Migration

A new Alembic revision after the current head drops
`runtime_web_gateway_identities.browser_profile`.

Models and repository data omit browser profile. Identity authentication retains:

- exact secret hash;
- non-revoked and non-expired identity;
- matching active authentication Session and user;
- non-disabled user;
- enabled Runtime Web configuration and matching authentication mode.

Long-lived authority revalidation uses identity ID, user, authentication Session,
and current authority without browser profile.

Removing Chromium settings changes the security fingerprint and invalidates
existing browser identities, bindings, and tickets during synchronized rollout.

## Public API and Generated Clients

`POST /runtime-web/v1/auth/shared-identity` no longer accepts
RuntimeWebBrowserProfileRequest. Its authenticated user/session boundary and
identity-secret response remain unchanged.

The Public OpenAPI document and Python/TypeScript generated clients are regenerated.
Admin APIs and Runtime Control protobufs are unchanged.

## Services Navigation and Interaction

`services` becomes a supported Session panel view in the canonical panel-view
parser and URL builder.

ChatSessionView:

- includes a Services navigation item using existing localized copy and icon;
- treats Services as a WorkspacePanel-owned supporting destination;
- maps it to `WorkspacePanel` active tab `services`;
- preserves the same behavior in desktop docked and mobile drawer layouts.

The Chat container enables Services polling only while that destination is visible.

RuntimeServicesPanel continues to expose:

- direct create through prepare and explicit confirmation;
- approve, reject, cancel, request again, and close;
- stable URL display, copy, and open;
- independent active and pending state;
- expiry and ended timestamps;
- installation-unconfigured and Runtime-unavailable states.

Create and approve dialogs stay open while the mutation is pending or failed and
close after the corresponding projection refresh succeeds. Related list and
endpoint queries are invalidated after mutations so Chat, Services, and endpoint
surfaces converge without waiting for polling.

## Reachability Semantics

The management UI distinguishes:

- exposure authority: pending, active, active+pending, expired, closed, inactive;
- installation configuration: configured or unconfigured;
- Runtime evidence: connected or unavailable.

It does not claim that an application port is unavailable merely because Runtime
evidence is absent. It does not perform active application health checks. Actual
proxy failures remain bounded endpoint responses and do not mutate approval state.

## Rollout and Recovery

The release rolls API, worker, Gateway, and Web together through the existing
snapshot pipeline. Existing Runtime pods need no protocol change.

On Gateway startup, the changed security fingerprint revokes pre-release identities
and clears incomplete broker exchanges. Users reauthenticate. Stable endpoints,
pending exposure requests, active cycles, and their deadlines remain.

Rollback to a release that requires the removed browser-profile column is not
supported after the migration. Recovery is roll-forward with the same
browser-neutral contract.

## Observability

Gateway failures remain content-free. Duplicate identity-cookie rejection records
only bounded policy outcome metadata and never cookie values. Browser vendor or
version is no longer an authorization or metric dimension.

Services UI errors use existing bounded API error mapping. Failed dialog mutations
retain user context and expose actionable localized feedback.

## Test Strategy

### Backend and migration

- Migration upgrades from the previous head and verifies the profile column is
  absent.
- Repository identity creation, authentication, redemption, and long-lived
  revalidation run without profile state.
- Gateway tests cover zero, one, identical duplicate, distinct duplicate, and
  multi-header identity cookies.
- Safe navigation redirects while programmatic unauthenticated HTTP and WebSocket
  traffic fail normally.
- Firefox/WebKit-like requests without Chromium client hints authenticate with one
  valid identity.
- Existing Origin, CORS, Service Worker, header normalization, revocation, expiry,
  approval, stream, and broker replay suites remain green.

### Main Web

- Shared and separate authentication start without a capability probe.
- Exact Main Web Origin and binding/ticket validation remain covered.
- Unified panel parsing and URL restoration include Services.
- Desktop and mobile stories expose the Services navigation destination.
- Dialog tests prove failure retention and success dismissal.

### E2E

- Existing real Runtime HTTP, SSE, WebSocket, shared-cookie, and separate-domain
  journeys remain.
- Product E2E enters Services from the Session panel, directly creates exposure,
  displays URL and active state, creates a simultaneous pending rerequest, cancels
  it independently, and closes the active cycle.
- The Services destination restores from its URL on desktop and mobile.
- Browser-neutral Gateway coverage executes equivalent authenticated requests
  without Chromium-specific headers. Available browser engines exercise the same
  identity contract; absence of one CI browser binary does not authorize a product
  restriction.

## Alternatives and Risks

- Stateless signed identity cookies were considered but add key rotation and
  revocation duplication without improving on the current opaque secret.
- Background application health probes were rejected because arbitrary GET
  requests can have side effects and do not define application-specific health.
- Removing browser-profile state reduces a defense introduced for one browser
  experiment; strict duplicate-cookie rejection, opaque secret validation, current
  authority revalidation, Origin/CORS policy, and credential stripping remain the
  cross-browser security boundary.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Browser-neutral opaque Gateway identity | REQ-1, REQ-2, ADR-D1 | `decided` |
| M2 | Exact raw Cookie cardinality with no history | REQ-2, ADR-D2 | `decided` |
| M3 | One-release browser-profile schema/config/API removal | REQ-6, ADR-D3 | `decided` |
| M4 | Unified Session Services navigation over the existing panel | REQ-3, REQ-4, ADR-D4 | `decided` |
| M5 | Honest authority and Runtime-evidence presentation | REQ-5, ADR-D5 | `decided` |
| M6 | Existing Session, approval, origin, transport, and credential boundaries | REQ-1, REQ-2, fixed constraints | `existing` |
| M7 | E2E-first cross-browser and management verification | REQ-6 | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Chromium/version/client-hint Gateway admission | REQ-1, REQ-6 | M1, M2, M6 | Gateway policy, server, settings, Helm, E2E | Searches contain no active browser allowlist or 426 profile path |
| Browser profile in identity state and contracts | REQ-6, ADR-D3 | Opaque identity and current authority | Migration, model, repository, services, Public API, generated clients | Schema and generated-surface tests |
| Main Web browser capability probe and browser-proof cookie | REQ-1, REQ-6 | Existing exact-origin identity establishment | Main Web routes, helpers, cookies, Gateway responses | Route/source search and browser tests |
| Disconnected Services panel navigation | REQ-3, REQ-4 | M4 | Session panel parser, navigation, active-tab mapping, refresh | desktop/mobile navigation and URL restoration tests |
| Premature dialog dismissal | REQ-5 | Success-owned dismissal | Services container/component state | mutation failure/success interaction tests |
| Application-unavailable label derived from generic Runtime state | REQ-5, ADR-D5 | Runtime-unavailable or unchecked evidence | Services state and locale copy | component stories and assertions |
| Existing Session permissions, approval cycles, broker exchange, Runtime transport | None | M6 | No replacement | existing regression suites |

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-09-13`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6, M7`
- Approved scope: Remove the unapproved Chromium-only restriction; retain
  request-local duplicate-cookie rejection and existing server-side authority;
  restore and complete the approved Services management surface; update current
  Specs; validate through browser, management, security, migration, and E2E
  evidence; and ship through a reviewed PR with required CI.
