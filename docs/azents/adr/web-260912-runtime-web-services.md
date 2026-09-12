---
title: "Runtime Web Services"
created: 2026-09-12
tags: [runtime, web, architecture, security, frontend, backend, infra]
document_role: primary
document_type: adr
snapshot_id: web-260912
---

# Runtime Web Services

- Snapshot: `web-260912`
- Document reference: `web-260912/ADR`
- Requirements: [web-260912/REQ](../requirements/web-260912-runtime-web-services.md)
- Decision mode: Autonomous for remaining material technical decisions
- Decision owner: Dedicated technical-design interviewee delegated by the requester

## Context

The confirmed requirements establish deterministic Session-and-port addresses,
nonblocking Agent requests with explicit user approval, existing Session permission,
indefinite pending requests, finite approved exposure, rerequest rather than extend,
and approval lifetime independent of Runtime replacement. They also require two
installation authentication modes and ordinary HTTP, streaming, SSE, and WebSocket
use without exposing Azents credentials to Runtime applications.

The current system has no Runtime Web Gateway. Runtime is an Agent-owned resource,
Runner connections are generation-fenced, and Terminal and transfer data planes use
separate bounded protocols. Existing Main Web authentication uses access and refresh
tokens stored in host-only cookies. These are reusable constraints and integrations,
not an existing Gateway implementation.

The requester confirmed the product behavior during the 2026-09-12 product-design
discussion, instructed that settled product decisions not be reopened, and delegated
remaining technical design and implementation. This ADR records those delegated
technical decisions separately from product authority.

## Fixed or Derived Outcomes

- The service address remains deterministic for a Session and port; per-cycle random
  origins are not a viable alternative.
- Approval mutations cannot be delegated to untrusted Runtime content.
- Approval and pending-request authority outlive individual Runtime and Runner
  connections, while each transport still requires current-generation fencing.
- Shared-cookie and separate-domain modes are both supported, one per installation,
  with no fallback.
- Redis is optional and cannot be the persistent authority for indefinite pending
  requests or approved exposure cycles.
- Exposure closure does not terminate the Runtime application process.

## Material Decision Map

- [x] D1 — trusted approval and authentication control surfaces on a reused origin
- [x] D2 — shared-cookie and separate-domain browser authentication/session model
- [x] D3 — general cross-service HTTP credentials, CORS, and approval-error contract
- [x] D4 — durable request/exposure authority and transactional state transitions
- [x] D5 — Gateway-to-Control-to-Runner stream ownership and multi-replica routing
- [x] D6 — expiration, revocation, rerequest, and active-connection transition rules
- [x] D7 — HTTP normalization, redirect, cookie, target, and compatibility envelope
- [x] D8 — installation configuration, deployment isolation, rollout, and recovery
- [x] D9 — initial finite duration and bounded resource defaults
- [x] D10 — parent-domain Gateway identity injection resistance

## Decisions

Decisions are appended below as the autonomous decision owner resolves them. Each
entry must state authority, alternatives, consequences, and required verification.

### web-260912/ADR-D1. Keep approval authority on the trusted control origin

**Authority:** `web-260912/REQ-2`, `REQ-3`, `REQ-10`, and the untrusted Runtime
boundary.

The exact configured Main Web/control origin exclusively renders authenticated
approval confirmation and executes approval, rejection, cancellation, and closure
mutations. Chat, Services, and pending endpoint navigation converge on one durable
request identity and revision. The service endpoint may return passive status or
send a top-level navigation to the trusted confirmation page, then return the user
to the deterministic service address after confirmation. An authenticated GET,
successful Gateway authentication, or service-origin data-plane grant is never an
approval.

Control mutations require current Main Web authentication, current Session
permission, the exact request revision, and the existing or equivalently strong
Main Web CSRF boundary. The control API accepts neither credentialed CORS nor a
same-site/shared-parent-origin trust rule from Runtime service origins. Return
destinations are constructed from configured platform origins and validated
identifiers rather than caller-provided URLs.

The Gateway rejects Service Worker script registration and update fetches on the
entire service hostname before redirects, cache handling, reserved-route handling,
or upstream proxying. Detection covers the standardized Service Worker script
request and browser fetch metadata without depending on one optional header.
Gateway-owned `Cache-Control: no-store` overrides upstream cache policy on every
service-origin response in the initial release so a warmed script cannot bypass
network rejection through `updateViaCache`. Reserved Gateway paths are routing
reservations, not a same-origin security boundary or management API.

**Consequences**

- Runtime applications cannot use Service Worker/offline/PWA behavior in the
  initial supported browser envelope. Dedicated/shared workers remain unaffected.
- Service responses forgo ordinary browser HTTP caching initially.
- Existing browser data is not remotely erased, and a previously installed worker
  is not claimed to be removed. Trusted-origin control mutations remain safe even
  in that condition.
- The policy must be present from the first response served under a newly admitted
  production service namespace.

**Rejected alternatives**

- Service-origin approval mutations authorized by a data-plane cookie: Runtime
  script shares the origin and could self-approve.
- Per-cycle origins: contradict deterministic Session-and-port addresses.
- Network Service Worker rejection without authoritative no-store behavior: does
  not establish safety for warmed registration/update resources.
- Login, redirect, or valid Gateway authentication as implicit approval: collapses
  authentication and explicit user confirmation.

**Required evidence**

- Both authentication modes prevent Runtime script from reading confirmation or
  CSRF material and from submitting control mutations.
- Classic/module registration, arbitrary paths/scopes, redirects, updates, and a
  warmed-cache `updateViaCache` probe do not install a worker.
- A seeded stale worker has no control-mutation authority and cannot renew
  upstream access.
- Stale/duplicate/racing request revisions remain transactionally safe.
- Credentials are absent from service URLs, application-visible bodies, upstream
  requests, and logs.

### web-260912/ADR-D2. Establish one opaque Gateway identity through two modes

**Authority:** `web-260912/REQ-3`, `REQ-8`, `REQ-9`, `REQ-10`, and ADR-D1.

Both installation modes establish the same short-lived opaque Gateway identity.
Its server-side record binds the authenticated user, originating authentication
Session, mode and monotonic mode epoch, issuance/expiration, revocation, and
exchange provenance. It is neither service approval nor control-plane
authentication. It is not bound to one service or Runtime generation; every target
request separately resolves current Session permission, approval, and expiration.

The parent-domain cookie contains only the opaque secret, uses a reserved
`__Secure-` name, `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, an explicit
configured Domain and bounded `Max-Age`. It is never exposed to Agent tools,
application code, URLs, upstream requests, or control APIs. Its validity cannot
exceed the access-authentication validity that established it. Main Web refresh
may replace it without extending service approval.

#### Shared-cookie mode

Main Web keeps its primary access and refresh credentials host-only and establishes
the separate Gateway identity cookie during trusted login/access refresh. It does
not widen the existing `az-token` or refresh cookie. Production Main Web primary
cookies use browser-enforced host-only naming when rollout compatibility permits.
Main Web/control never accepts the parent-domain Gateway identity as its own
authentication, so a sibling-origin cookie cannot select a control identity.

#### Separate-domain mode

The service parent domain hosts a trusted authentication broker. Main Web first
establishes a short-lived browser-held broker nonce, then issues a 30-second
single-use ticket bound to that nonce, user, authentication Session, mode epoch,
and validated destination. A trusted Main Web document sends the ticket only in a
top-level HTTPS form POST body to the exact broker origin. The broker verifies the
exact Origin and browser nonce, atomically consumes the ticket, freshly validates
authority, and sets the common Gateway identity cookie.

The broker renders a no-store trusted completion document before starting
same-site navigation to the deterministic service address. The flow does not rely
on a cross-site POST followed only by a 303 to carry a newly set Strict cookie.
Transient binding cookies are host-only, short-lived, deleted after settlement,
and may use `SameSite=None; Secure` only where browser testing proves it necessary.
IP address, User-Agent, or a nonce submitted alongside a stolen ticket is not
browser binding.

#### Common integrity and revocation

Gateway rejects duplicate reserved cookies, strips every platform credential before
upstream forwarding, and strips Runtime responses that attempt to set or delete
reserved names. Exact configured Origin and the Main Web CSRF boundary protect
control mutations; sibling-domain and same-site status never imply trust. A stale
cookie cannot authorize access when its authentication Session, mode epoch, target
Session permission, or exposure approval is invalid.

Logout and authentication-Session revocation invalidate identities server-side.
Mode change increments the epoch and rejects old tickets and identities without
fallback or rollback resurrection. Initial long-connection targets are authority
checks every five seconds and closure within ten seconds of revocation; known
service expiration is enforced at its own deadline.

**Rejected alternatives**

- Widen the existing Main Web access or refresh cookie: exposes control
  authentication at the hostile sibling-domain boundary.
- Per-service host-only grants: require target bootstrap and fail ordinary first
  cross-service requests.
- URL/fragment tickets, Runtime application credentials, and refresh at Gateway:
  violate credential-boundary requirements.
- A supposedly browser-bound ticket without independent browser-held proof:
  redeemable from another client that obtained the ticket.

**Required evidence**

- Both modes support sibling service requests without manually opening the target,
  while denying unapproved, unauthorized, and cross-Session source origins.
- A second browser cannot redeem a stolen ticket; wrong Origin/nonce, replay,
  simultaneous consume, expired epoch, and interrupted exchange fail closed.
- Chromium, Firefox, and WebKit establish the broker and Strict data-plane cookie
  with third-party cookies disabled, including the completion-page transition.
- Duplicate/tossed cookies and Runtime `Set-Cookie` cannot select a different
  user, affect Main Web control authentication, or reach an upstream application.
- Logout, revocation, Runtime replacement, and mode epoch changes have the
  required independent effects.

### web-260912/ADR-D3. Authorize generic cross-service HTTP within one root Session

**Authority:** `web-260912/REQ-3`, `REQ-8`, `REQ-10`, `REQ-11`, ADR-D1, and
ADR-D2.

Concrete Agent Session identity remains part of every deterministic endpoint,
request, and approval cycle. For cross-service permission only, subagent Sessions
resolve to their canonical root Session under existing Team/User access rules.
Source and target must share that root, Workspace, and Agent. Common Workspace
membership or one user's access to multiple unrelated Sessions is insufficient.
Each target still requires its own active approval.

Actual cross-origin requests require a valid Gateway identity, current target
Session permission, current target approval and deadline, one non-null Origin that
resolves to an active exact source endpoint, and the common permission boundary.
Malformed, unknown, `null`, cross-root, or inactive-source origins fail before
proxying. Same-origin browser assets use normal target checks. Safe top-level
GET/HEAD navigation may enter trusted authentication/approval navigation.
Cross-origin non-navigation requests without Origin fail closed; Fetch Metadata
must establish the permitted browser category rather than absence being trusted.
Unsafe form/navigation requests do not redirect into automatic mutation replay.

The Gateway handles a valid CORS preflight locally and never contacts an
application. It validates source/target boundary, method and normalized bounded
request headers without requiring credentials or treating preflight as approval.
Permitted preflight returns `204`, exact reflected origin, credentials true,
methods `GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS`, a bounded initial request
header set, `Max-Age: 0`, and `Vary` for Origin, requested method and requested
headers. Invalid origin/header negotiation returns `403`; unsupported methods
return `405`. Ordinary OPTIONS without preflight fields is an authenticated app
request.

The initial cross-origin request-header set is Accept, Accept-Language,
Content-Language, Content-Type, Authorization, Range, X-Requested-With,
X-CSRF-Token and X-XSRF-Token. Reserved platform, proxy, and forwarding headers
are rejected. Gateway replaces upstream `Access-Control-*` fields so applications
cannot broaden policy. Authorized callers receive consistent CORS fields on
Gateway-owned errors; forbidden origins receive no reflected permission.

Programmatic failures use bounded JSON codes: `401` identity required, `403`
origin or disclosed permission denial, `404` private/not-found-safe target, `409`
approval pending or required, `410` expired/closed without replacement request,
`429` admission limit, `502` approved application unreachable, `503` Runtime or
platform dependency unavailable, and `405` unsupported method. Safe navigation
may reach the trusted D1 UI. API calls never receive successful-looking login
HTML, and failed mutations are never automatically replayed. Genuine application
errors remain upstream responses.

**Consequences**

- Application fetches use the ordinary `credentials: "include"` browser contract;
  Gateway does not inject secrets or rewrite code.
- A subagent endpoint remains distinct even though authorization resolves its
  root; endpoint identity is never normalized to the root Session.
- Clients without trustworthy Origin/Fetch Metadata and requests using arbitrary
  custom headers have an explicitly restricted compatibility envelope.

**Rejected alternatives**

- Reflect every service-suffix Origin: allows an app in one Session to read a
  service in another Session under the user's shared Gateway identity.
- Proxy preflight to the application: exposes unapproved targets and leaves the
  credential-free negotiation authorization undefined.
- Let app CORS headers broaden the platform policy: delegates the Session boundary
  to untrusted code.
- Interpret FE/BE roles or dependency declarations: contradicts the generic HTTP
  service requirement.

**Required evidence**

- Root/subagent permission and distinct endpoint identity, cross-root denial,
  source/target approval and expiration, Origin-null/no-CORS/form cases.
- Local preflight without upstream traffic, exact header/method bounds, hostile
  upstream CORS replacement, and readable authorized error responses.
- Private target non-disclosure, Runtime replacement, and absence of mutation
  replay.

### web-260912/ADR-D4. Persist dedicated endpoint, request, and cycle authority

**Authority:** `web-260912/REQ-1` through `REQ-7`, `REQ-11`, `REQ-13`, and the
repository's PostgreSQL transaction boundary.

PostgreSQL owns dedicated relational endpoint, request, exposure-cycle, and
idempotency-receipt records. Toolkit State, Runtime rows, Redis, and process memory
are not approval authority.

An endpoint binds the concrete Agent Session and port to one random opaque hostname
key stored once. It has a unique `(agent_session_id, port)`, a unique hostname key,
an authority revision, and transactionally maintained references to the current
pending request and current cycle. Runtime generation is not endpoint identity.
Address lookup may get-or-create this bounded endpoint but creates no request,
approval, or Runtime.

A request has an immutable ID, endpoint, requester and execution correlation,
immutable requested parameters, monotonic revision, explicit
pending/approved/rejected/cancelled outcome, actor and timestamps. A partial unique
constraint permits at most one pending request per endpoint. It has no elapsed-time
expiration. An exposure cycle has an immutable ID and originating request,
approver, approval instant, fixed expiration and end/supersession metadata. A
partial unique constraint permits at most one current cycle, but every authority
check still evaluates expiration and closure rather than trusting the pointer.

A durable actor/execution-scoped operation key maps retryable URL/request/direct
creation/control calls to their recorded result. This receipt may be a supporting
table but is required so retry after approval or rejection cannot create a new
request. Request and cycle history, with content-free actor/outcome/timestamp
fields, is the durable lifecycle audit; Chat transcript output is only an immutable
request reference.

The domain operation repository owns SQL, authorization reads, and transaction
lifetime. An endpoint row lock serializes transitions:

- Request returns the idempotency result or current pending request, otherwise
  inserts one without changing the active cycle.
- Approval reauthorizes current Session access, validates exact request/revision,
  records approval, supersedes the prior current cycle, creates one new cycle from
  one database approval time, and advances endpoint references/revision atomically.
- Direct user creation records explicit confirmation and request+cycle in one
  idempotent transaction.
- Cancel/reject affect only the expected pending request and revision.
- Close affects only the expected current cycle; a stale close cannot terminate a
  later approval.
- Exact repeated mutations return their recorded outcome; conflicting stale
  mutations fail rather than retargeting current state.

Database time is authoritative for approval and expiration. Expiry does not require
a scheduler to become effective; later materialization is bookkeeping. Session
deletion owns cascade cleanup, while Runtime removal does not. History and receipts
remain for the supported replay/audit window, with bounded payloads, admission and
pages. Cleanup never makes an old cycle current.

After commit, services publish best-effort invalidation. Lost publication cannot
extend authority because polling and explicit deadlines read PostgreSQL. Empty
Redis/memory reconstructs new access from PostgreSQL plus current Session/Runtime
checks, never from Runtime claims or cached streams.

**Rejected alternatives**

- Toolkit State aggregate: weak indexed hostname lookup, coarse contention, and
  awkward lifecycle history.
- Volatile approval state: incompatible with indefinite pending and Runtime
  independence.
- One pending/active state flag: cannot model active plus rerequest.
- Multiple pending requests: ambiguous approval and unbounded duplicate admission.
- A second audit event source of truth: adds a redundant consistency boundary.

**Required evidence**

- Concurrent endpoint creation, request deduplication, retry after completion,
  direct-create retry, and concrete-Session cascade.
- Concurrent approve/reject/close, stale close versus new approval, active plus
  pending, and exact database deadline.
- Failed commit publishes no invalidation; lost invalidation and empty coordination
  still converge; Runtime replacement retains authority.

### web-260912/ADR-D5. Route live bytes through the owning Control replica

**Authority:** `web-260912/REQ-7`, `REQ-8`, `REQ-11`, `REQ-13`, ADR-D3,
ADR-D4, current multi-replica Runtime Control deployment, and current Runner
network restrictions.

The Control replica accepting a dedicated trusted Gateway-to-Control bidirectional
web-proxy RPC becomes the immutable live owner of that request or connection. A
metadata-only open/cancel intent travels through the existing Runner Control path.
The current Runner opens a dedicated authenticated `ConnectWeb` RPC at its existing
configured Control service destination. If that RPC reaches another replica, the
receiver joins it to the owner through a new mTLS-authenticated Control-only
bidirectional relay RPC. Relays have one hop maximum.

HTTP/SSE/WebSocket bytes exist only in bounded process-memory queues and the three
live RPCs. They never enter PostgreSQL, Redis, object storage, ordinary Runtime
operation reply streams, or transcript events.

Each owner stores a local tunnel record with endpoint and approval revision,
approval deadline, exact current Runtime and Runner generation, unpredictable
one-use join nonce, registration state, and byte budgets. A short routing record
contains owner boot identity, deployment-controlled routable address, tunnel and
nonce binding, Runtime generation, registration deadline, and renewable owner
lease. Addresses never come from Runtime, Runner, application, or user input.

The non-Redis-capable routing baseline uses PostgreSQL short-lived metadata without
body bytes or approval truth. Redis may optimize expendable coordination but is not
the sole multi-replica registry. Process-local routing is valid only for explicit
single-process composition. A receiver authenticates and fences the Runner, then
the owner independently checks boot identity, tunnel, nonce, generation, lease and
deadlines. Duplicate joins fail.

Per-owner addresses use deployment-controlled pod/headless or equivalent Docker
routing, verified service TLS identity, Control boot identity, and an explicit
Control-to-Control network policy. Runner credentials do not authenticate the
inter-Control hop.

Owner, relay, or Gateway loss terminates the affected transport without moving
queues or replaying application requests. Runtime replacement closes old-generation
tunnels but leaves durable endpoint/request/approval state. Drain stops new
admission and retains existing connections only within configured drain and
authority deadlines before closing them. Approval expiry and revocation override
transport leases.

Queues and limits are byte-based per stream, owner, Runtime, endpoint and user as
applicable. Typed frame and cumulative bounds are checked before enqueueing;
downstream capacity applies backpressure. Registration/join, idle progress, total
transport lifetime, and cancellation have bounded timeouts. Exhaustion fails the
affected connection without blocking Runtime lifecycle or ordinary Control work.

**Rejected alternatives**

- Two independent RPCs behind one load-balanced service: no replica rendezvous.
- Terminal broker: stores PTY bytes/replay and invalidates Terminal authority on
  Runtime replacement.
- File Transfer: object-staged complete-file semantics are not live HTTP.
- Single Control replica: contradicts current two-replica/autoscaling operations.
- Exact-owner Runner callback: fewer hops but expands Runner egress, callback
  address trust, and TLS validation; the relay preserves its current destination.

**Required evidence**

- Force Gateway admission on Control A and Runner arrival on B; stream both ways
  without shared byte storage under Redis and non-Redis configurations.
- Owner/relay loss, stale boot record, expired lease, duplicate nonce, forged
  address, TLS-role rejection, drain, and bounded slow-consumer behavior.
- Runtime replacement retains approval but prevents old frames from joining.
- Ambiguous POST transport failure produces no automatic replay.

### web-260912/ADR-D6. Bind transports to exact deadlines and cycle revisions

**Authority:** `web-260912/REQ-3`, `REQ-5` through `REQ-7`, `REQ-11`, ADR-D3,
ADR-D4, and ADR-D5.

Every new application request reads current PostgreSQL identity, authentication
Session, target Session permission, current cycle, closure, and expiration
authority. A stale positive cache never admits a new request.

Gateway and the owning Control schedule the approved deadline directly. At
`now >= expires_at`, new upstream admission stops and all remaining HTTP, SSE, and
WebSocket transports are cancelled. Known expiration does not wait for a poll, and
Runtime downtime, heartbeat, owner lease, traffic, or pending rerequest cannot move
the deadline. The deadline is the authority boundary and timer target, not a
zero-scheduling-jitter promise.

Active streams revalidate authentication and permission at least every five
seconds and close no later than ten seconds after committed loss. Post-commit
notifications accelerate this but are not required for correctness. Authentication
Session revocation closes only streams using that authentication Session; Session
permission loss closes that user's streams; neither revokes the service cycle for
other authorized users. Explicit exposure closure blocks new database admission
immediately and closes endpoint transports within the same bound.

The endpoint carries a monotonic close barrier/revision as durable evidence so a
rapid close followed by approval cannot cause an older stream to miss the closure.
A pending rerequest does not change the active cycle or streams.

When approval installs a replacement cycle, new requests bind to it. Already
admitted bounded ordinary HTTP requests may finish only before the earlier of their
original transport deadline and original cycle expiration and continue permission
checks. Explicit closure overrides that allowance. Old SSE, WebSocket, and other
unbounded streaming connections close with a bounded `cycle_replaced` outcome and
must reconnect. Streams are never silently rebound and request bodies are never
replayed against another cycle or Runtime.

Expiry, replacement, and cycle closure do not cancel a pending request. Cancel and
reject target the exact pending request separately. Agent close identifies the
cycle and revision it observed; a stale close cannot terminate a later cycle.
Runtime replacement closes obsolete transports only and leaves approval and its
original deadline intact.

Before upstream response headers, Gateway uses ADR-D3 errors. After application
headers, it terminates the stream rather than appending platform JSON to
application bytes. WebSocket close codes/reasons are sanitized and assigned
consistently by the Design. Clients may reconnect or submit a fresh request after
authority restoration; Gateway never automatically retries unsafe methods.

**Rejected alternatives**

- Polling-only expiration or notification-only revocation: extends authority after
  known deadline or lost publication.
- Apply the new cycle deadline to old streams: silently extends old admission.
- Revoke the service when one user loses access: harms other Session users.
- Cancel pending requests on expiry/close: conflates independent state.
- Unbounded in-flight completion: becomes indefinite old-cycle access.

**Required evidence**

- Deadline during continuous HTTP/SSE/WebSocket, lost invalidation, and authority
  store failure.
- Per-user logout while another user remains connected.
- Pending rerequest unchanged; bounded ordinary completion; long-stream replacement
  closure; close then rapid reapproval with missed notification.
- Stale Agent close, Runtime replacement, and absence of mutation replay.

### web-260912/ADR-D7. Relay typed HTTP semantics to an exact loopback port

**Authority:** `web-260912/REQ-8`, `REQ-10`, `REQ-11`, ADR-D1, ADR-D3,
ADR-D5, and ADR-D6.

Gateway terminates public HTTP/1.1 and HTTP/2. The typed relay terminates at a
Runner `aiohttp` HTTP/WebSocket client that connects only to numeric loopback
`127.0.0.1` or `[::1]` at the endpoint's approved port. It performs no DNS
resolution, environment-proxy use, automatic redirect following, or automatic
response decompression.

The initial envelope supports GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS,
streamed request/response bodies, SSE, and ordinary HTTP/1.1 WebSocket upgrade.
It rejects CONNECT, TRACE, raw TCP/UDP, WebTransport, request trailers, and
HTTP/2 extended-CONNECT WebSocket. Request bodies, headers, frames, queues,
bandwidth, idle progress, and transport lifetime are bounded. Responses have no
cumulative byte cap and remain live-streamed, including downloads above the prior
64 MiB proposal.

Headers remain ordered pairs so duplicates such as Set-Cookie are not collapsed.
The earliest trusted parsing boundary rejects malformed names/values, CR/LF,
conflicting Content-Length, ambiguous transfer framing, and trailers. Typed body
events generate upstream framing. Gateway removes hop-by-hop and
Connection-nominated fields, caller Forwarded/X-Forwarded/X-Azents/proxy-control
fields, and reserved platform cookies. It sets `Host: localhost:<port>` and
validated public forwarded host/protocol/port.

Application Authorization is supported independently of Gateway authentication.
Explicit Azents platform credentials are rejected rather than forwarded, without
rejecting every Bearer value or guessing from JWT shape alone.

ADR-D3 origin authorization runs before normalization. An Origin equal to the
target public endpoint may be normalized to its fixed loopback origin for local
server compatibility, and the origin portion of a matching Referer may follow.
An authorized different service Origin remains different and is never disguised
as target same-origin. Other invalid origins are rejected.

Gateway strips reserved Set-Cookie names. Permitted application cookies preserve
values and duplicates, remove Domain, enforce Secure, and use a bounded valid
representation. Gateway removes upstream Access-Control fields, enforces ADR-D3
CORS and ADR-D1 no-store, and preserves compression bytes consistently with
Content-Encoding.

Redirects are never followed. Relative locations pass after parsing. HTTP(S)
locations for the same exact numeric loopback port are rewritten to the public
endpoint. Other loopback ports, private/link-local/metadata literals, localhost
aliases, internal service names, embedded credentials, unsupported schemes, and
ambiguous Refresh are blocked. External HTTP(S) named-host redirects may reach
the browser but receive no Gateway fetch or platform credential.

Platform approval/error documents receive strict document CSP, framing protection,
no-store, and no-referrer. Proxied apps receive `frame-ancestors 'none'`,
Referrer-Policy no-referrer, COOP same-origin, and an initially restrictive
Permissions-Policy for camera, microphone, geolocation, payment, and device
access. Gateway does not impose a broad script/style CSP, rewrite HTML/JavaScript,
inspect bodies, or buffer/store complete responses.

**Rejected alternatives**

- Raw byte tunnels or arbitrary target names: lose enforceable HTTP and SSRF
  boundaries.
- Blanket Origin rewriting: hides cross-service requests from application policy.
- Cumulative response limit: breaks legitimate live streaming and downloads.
- Body rewriting: breaks compression, signatures, CSP, streaming, and source maps.
- Broad CSP worker restriction: removes ordinary worker compatibility beyond D1.

**Required evidence**

- Duplicate/framing attacks, HTTP/2 ingress, credential stripping, same versus
  cross-service Origin, and local/private/external redirect behavior.
- Compressed streaming and responses above 64 MiB with bounded memory; request
  overflow, SSE/WebSocket backpressure and deadline cancellation.
- Malicious upstream cookie/cache/CORS/security fields and no automatic redirect
  or unsafe-method replay.

### web-260912/ADR-D8. Deploy Gateway independently with a monotonic auth epoch

**Authority:** `web-260912/REQ-7`, `REQ-9`, `REQ-11`, `REQ-12`, `REQ-13`,
ADR-D2, ADR-D4, ADR-D5, and current Helm deployment constraints.

Gateway is a separate entrypoint/process in the existing server application and
image, with its own Deployment, Service, wildcard Ingress/TLS, probes, resources,
autoscaling, and bounded drain. The trusted authentication broker uses its
configured service-parent host. Gateway reads PostgreSQL authority and uses
authenticated internal Control RPCs. Runtime Control adds D5 per-owner routing,
mTLS identity, headless/per-owner reachability, and a narrow Control-to-Control
NetworkPolicy. Runner retains its current trusted Control service destination.

Helm configuration includes feature enablement, auth mode, a monotonic auth
configuration version, exact Main Web/broker origins, service suffix/parent and
cookie domain, TLS secret reference, internal Control trust/client identity,
finite exposure duration, and traffic/drain limits. Secret values have no chart
defaults or public projection.

Production requires HTTPS, exact origins, valid hostname/cookie relationships, and
usable TLS. Shared mode requires every server receiving the configured parent
cookie to be deployment-controlled and trusted for cookie handling, without
trusting Runtime content. Separate mode requires a different registrable site and
a broker inside the service parent. Public-suffix cookie domains, wildcard control
origins, ambiguous suffix matches, and inconsistent broker/host combinations are
rejected. Insecure HTTP is explicit local-only configuration, not a fallback or
production browser proof.

PostgreSQL stores the highest accepted auth configuration version and its canonical
security fingerprint. The fingerprint includes mode, enabled state, trusted
origins, cookie scope, address namespace, and authentication trust inputs; ordinary
tuning does not require reauthentication. Equal version requires equal fingerprint,
lower version cannot serve or issue Gateway authentication, and a validated higher
version atomically advances the active epoch. Conflicting rollout replicas fail
Gateway-specific readiness/work without disabling unrelated Chat/Public API.
Request and stream checks verify the current epoch rather than relying only on
startup.

A mode/security change invalidates old Gateway identities and exchange tickets and
closes old transports under ADR-D6. Durable pending requests and approved cycles
remain; users authenticate through the new mode without another service approval,
and original expiration continues. Disablement likewise blocks/ends Gateway
transport while retaining logical state. Reenablement advances the epoch and never
revives expired cycles.

Invalid configuration fails readiness explicitly. Database/epoch authority outage
admits no uncertain authentication or proxying. Old replicas refuse work after an
advance. Interrupted broker exchange starts a new exchange without reusing a
consumed ticket. Missing Gateway capability is projected as disabled/unconfigured;
an unsupported Runner is transport-unavailable but does not revoke approval.

Migrations are additive. Rollback does not edit or destructively downgrade executed
schema, lower auth version, resurrect old credentials, or add legacy fallback. A
rollback binary must understand the current schema/config contract or leave Gateway
disabled. Runner advertises `runtime-web-http.v1`; mixed unsupported combinations
fail closed.

**Rejected alternatives**

- Embed Gateway traffic into Public API/Chat deployment: couples untrusted
  streaming load and drain.
- Infer trusted domains from request Host or use an unsafe same-origin path
  fallback: weakens configured authority.
- Mode name alone or reversible fingerprint as epoch: rollback can resurrect old
  credentials.
- Delete approvals/Runtime/Session on mode switch: conflates browser identity with
  durable product state.

**Required evidence**

- Version/fingerprint conflict, lower-version restart, concurrent advance,
  mixed-mode replicas, rollback, disable/reenable, and old-stream closure while
  approval persists.
- Invalid domain/TLS combinations, DB outage, local-insecure production rejection,
  service-role TLS/network rejection, two-replica drain, and unsupported Runner.

### web-260912/ADR-D9. Start with bounded installation-owned limits

**Authority:** `web-260912/REQ-5`, `REQ-6`, `REQ-11`, `REQ-12`, ADR-D5,
ADR-D6, and ADR-D7.

The default approved exposure cycle is two hours, configurable by the operator
between five minutes and eight hours. Users and Agents do not request arbitrary
durations initially. Approval displays the configured duration and deadline, and
captures that duration so later configuration changes do not modify a cycle.
Pending requests remain indefinite. There is no service idle expiry, automatic
renewal, extend operation, or cumulative lifetime cap; reapproval creates another
finite cycle. Two hours is a delegated technical baseline, not a
requester-specified number.

Logical defaults are sixteen stable endpoints and pending requests per concrete
Session, one pending request per endpoint, four active endpoints per Session, and
sixteen active endpoints per owning Agent. Configuration ranges are endpoints
1–64, active Session endpoints 1–16, and active Agent endpoints 1–64. Logical
aggregation uses Agent rather than optional Runtime identity, so absence or
replacement does not reset quota. Valid distinct endpoint cycles count; history
does not, replacement approval does not double-count, and expiry stops counting at
the deadline before cleanup. Stable endpoint mappings count until Session cleanup.
There is no creator-user quota for shared Session approvals.

Live defaults are:

- HTTP/SSE: endpoint 32, accessing user 64, owning Agent bucket 128.
- WebSocket: endpoint 4, accessing user 8, owning Agent bucket 16.
- Bandwidth in each direction with one-second burst: user 8 MiB/s and Agent
  32 MiB/s.

Operator ceilings are HTTP/SSE 128/256/512, WebSocket 16/32/64, user bandwidth
32 MiB/s, and Agent bandwidth 128 MiB/s. The actual authenticated user is charged
across authentication Sessions. Agent identity owns the Runtime bucket across
generation changes. Admission is charged once per tunnel, not for the relay hop,
and retained until termination. Shared live counters use lease-backed admission
and recovery rather than one replica's local counter.

Size defaults and hard ceilings are:

- request headers 32/64 KiB; response headers 64/256 KiB;
- request body 16/64 MiB;
- body frame 64/64 KiB;
- assembled WebSocket message 1/8 MiB;
- queued bytes per stream/direction 256 KiB/1 MiB;
- aggregate live body buffers per process 64/256 MiB.

Header count and metadata parsing are also bounded. There is no cumulative response
body limit; bandwidth, backpressure, process budgets, idle progress, and deadlines
bound it.

Timeout defaults are three-second loopback connect; response head within thirty
seconds after request-body completion or connect for bodyless requests; ordinary
idle sixty seconds and absolute ten minutes; SSE/WebSocket idle five minutes and
absolute two hours; registration/join ten seconds; ticket thirty seconds;
authority polling at most five seconds and committed revocation closure within ten
seconds. Every transport is also bounded by its admitted cycle deadline. Gateway
identity cannot outlive establishing access authentication. Adjustable transport
timeouts have validated positive ranges and initial upper bounds twice the defaults,
but cannot override approval, ticket, or revocation boundaries.

Quota failure uses ADR-D3 `429`; request body overflow uses `413`, request headers
`431`, and response/stream violations use bounded Gateway failure or closure.
Failures do not change request or approval state.

**Required evidence**

- Concurrent approvals at limits, approval while Runtime absent, replacement
  without reset, reapproval without double count, and shared-user accounting.
- Lost lease recovery, process/stream buffer exhaustion, slow peers, large
  responses without cutoff, and deadlines during continuous traffic.

### web-260912/ADR-D10. Require an enforced `__Http-` browser envelope

**Authority:** `web-260912/REQ-3`, `REQ-9`, `REQ-10`, ADR-D1, ADR-D2, and the
Chromium cookie-prefix/client-hint probe executed during design.

ADR-D2's parent-domain cookie name is superseded by a reserved `__Http-` Domain
cookie with Secure, HttpOnly, SameSite=Strict and Path=/. In an enforcing browser,
Runtime JavaScript cannot create the absent tuple because it cannot supply
HttpOnly. There is no `__Secure-` fallback.

Identity issuance performs a trusted-origin capability probe with unpredictable
host-only state. It proves that ordinary JavaScript cookie creation works,
JavaScript `__Http-` creation fails, and server-set Secure+HttpOnly `__Http-`
creation succeeds. The probe is bound to the authenticated exchange and cleaned
up. Missing or ambiguous evidence fails.

Issuance evidence alone is not request provenance. Every application admission
therefore requires a code-owned supported browser engine/version profile with a
tested browser-controlled, version-bearing signal that Runtime JavaScript cannot
create or modify. User-Agent alone is never sufficient. The initial profile
requires consistent Fetch Metadata plus an accepted UA Client Hint version.
Unknown, missing, inconsistent, or unsupported profiles return `426` or a passive
upgrade page before application content, even with a valid identity cookie.

Cookie-authenticated custom/nonbrowser clients and browsers without protected
version evidence are outside the initial data-plane envelope. Firefox and WebKit
remain unsupported until an equivalent protected version signal and prefix
conformance are proven; they are never admitted by a User-Agent-only exception.
Operators cannot weaken this code-owned minimum or select `__Secure-`.

The local Chromium 152 TLS probe established that service-origin JavaScript could
create a parent-domain `__Secure-` cookie, could not create `__Http-`, and could
not replace the observed Chromium UA Client Hint or User-Agent on a same-origin
fetch. This is evidence for one exact profile, not proof for other versions.

**Consequences**

- Initial browser compatibility is intentionally narrower than accepting an
  injectable shared cookie on every engine.
- A custom client that forges a complete browser request and presents a stolen
  bearer remains a credential-theft threat, not Runtime JavaScript injection; it
  receives no control-plane authority.
- Runtime Set-Cookie stripping, duplicate rejection, trusted receiving hosts, D3
  source/target permission, and host-only Main control cookies remain mandatory.

**Required evidence**

- Server/JavaScript prefix behavior plus a protected version signal for every
  admitted version.
- A non-enforcing browser with genuine Fetch Metadata, spoofed User-Agent and an
  attacker-valid grant remains denied because protected version evidence is absent.
- Missing tuple, Domain/Path/name variants, stale documents, probe tampering,
  logout, expiry and mode changes.
