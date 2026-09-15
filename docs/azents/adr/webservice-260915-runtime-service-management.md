---
title: "Runtime Web Service Management Decisions"
created: 2026-09-15
updated: 2026-09-15
tags: [runtime-web, runtime, architecture, security, api, frontend]
document_role: primary
document_type: adr
snapshot_id: webservice-260915
---

# Runtime Web Service Management Decisions

- Snapshot: `webservice-260915`
- Document reference: `webservice-260915/ADR`
- Requirements: [webservice-260915/REQ](../requirements/webservice-260915-runtime-service-management.md)
- Decision mode: Collaborative
- Decision owner: Requester

## Context

The confirmed Requirements replace the current Session-scoped approval resource
with one directly managed service for each Agent and local port. Every Session of
the Agent and Agent settings must observe the same service, each service must have
a short row-lifetime public address, Agent Runtime removal must remove the service,
and the Agent tool surface must be limited to request, list, and idempotent close.

The current implementation persists separate endpoint, request, cycle, and
operation-receipt authority. Endpoint identity is `Agent Session + port`, hostname
keys are random, Gateway admission requires a current approval cycle, Public API
routes and generated clients expose request/cycle actions, and the Runtime Web
Toolkit exposes prepare/request/list/cancel/close. The Runtime removal workflow
does not currently clean Runtime Web services.

This ADR supersedes only the service-management, ownership, and exposure-state
decisions that conflict with `webservice-260915/REQ`. The existing Runtime Web
authentication, browser isolation, origin, redirect, Service Worker, framing,
transport, resource-bound, and Runtime-generation decisions remain authoritative
unless this snapshot explicitly replaces one of their service-management inputs.

## Fixed or Derived Outcomes

- Service identity and uniqueness are `Agent + numeric local port`. Session and a
  particular logical Runtime row are not service identity.
- The service row is removed during permanent Agent Runtime product-state cleanup.
  Recreating the Runtime does not restore the row, and recreating the same port
  receives a new public hostname.
- Request, approval, rejection, cancellation, requester provenance, approval
  provenance, renewal, and pending state are removed from service authority and
  user presentation.
- A service first created by an Agent stores 1 hour as its initial selected
  duration.
- Agent Runtime capability must be currently managed for service management to be
  exposed or mutated. Gateway admission additionally requires a current ready
  Runtime generation.
- The Session side panel and Agent settings use one Agent-scoped service contract
  and one authoritative server projection.
- The trusted Main Web control origin continues to own authentication completion
  and Off-to-On activation. Runtime service-origin content receives no control
  mutation authority.
- Gateway access is denied immediately when the service is Off, expired, deleted,
  or lacks a managed and ready Runtime. Database time remains the deadline clock.
- Agent-wide service identity replaces the prior same-root-Session endpoint
  boundary for cross-service origin checks; exact source lookup, current source and
  target state, user authorization, and existing CORS protections remain required.
- Obsolete Session/request/cycle fields are removed from Runtime Web stream
  authority. The existing exact protocol fingerprint provides mixed-version
  rejection without a compatibility reader or fallback.
- Public API, generated clients, TRPC, Agent tool presentation, trusted activation
  UI, Session panel, Agent settings, tests, fixtures, and Living Specs change as
  one coherent contract replacement.

## Material Decision Map

- [x] `webservice-260915/ADR-D1` — durable service and exposure source of truth,
  expiration representation, and optimistic concurrency
- [x] `webservice-260915/ADR-D2` — short random DNS-safe hostname generation and
  collision handling
- [x] `webservice-260915/ADR-D3` — service addressing and idempotency contract
  across Public API and Agent tools
- [x] `webservice-260915/ADR-D4` — migration and rollout boundary for legacy
  Session endpoints, requests, cycles, receipts, and stream contracts

## Decisions

### webservice-260915/ADR-D1. Keep current service and exposure authority in one row

**Authority:** `webservice-260915/REQ-1`, `REQ-3` through `REQ-6`, `REQ-8`, and
the PostgreSQL transactional authority retained from the existing Runtime Web
design.

One durable service row owns the Agent, numeric local port, deterministic hostname
key, label, selected duration, nullable exposure deadline, monotonic mutation
revision, and timestamps. `(agent_id, port)` is unique. No separate request,
approval, cycle, exposure-window, requester, approver, creation-origin, or exposure
history entity participates in current service authority.

The selected duration is restricted to 3,600, 21,600, or 86,400 seconds. An
Agent-created service begins with 3,600 seconds selected and no exposure deadline.
At database time `now`, a service is On only when its exposure deadline is later
than `now`; a null, elapsed, or equal deadline is Off. Expiration therefore changes
the effective state without a background writer, queue, Redis key, or sweeper.
Reads return no current expiration for an effectively Off service even if the
stored deadline is an elapsed value.

Turning On or resetting expiration assigns `database_now + selected_duration`.
Turning Off clears the deadline. Changing duration updates only the selected value.
Deleting removes the row. Human mutations use the service revision to reject stale
displayed-state writes. Agent close locks the current service row and is
idempotent: it clears a future deadline or succeeds unchanged when the service is
already effectively Off.

Gateway admission and long-connection authority use the same absolute exposure
deadline. Admission always re-evaluates the deadline against database time, and
known-deadline stream closure remains enforced at that deadline. A cleanup job may
normalize elapsed deadlines for storage hygiene, but it is never state authority
and cannot be required for correct denial.

**Consequences**

- The persisted model directly matches the user-visible service state and has one
  concurrency boundary.
- Expiration remains correct through process restarts and optional Redis loss
  without periodic mutation.
- On, Off, reset, duration change, close, and deletion races are serialized on one
  row and exposed through one monotonic revision.
- Product history does not retain prior exposure windows or the users or Agents
  that initiated them.
- Existing request, cycle, current-pointer, close-barrier, and end-reason state is
  removed rather than renamed.

**Rejected alternative**

- Keep a service row plus immutable exposure-window rows and a current pointer:
  this preserves historical window identities but recreates the split cycle
  authority, cleanup, pointer, and race model without a confirmed product,
  security, or operational requirement for that history.

**Required evidence**

- Repository concurrency tests cover stale human revisions, simultaneous On/Off,
  duration-change versus reset, duplicate Agent close, expiry boundaries, and
  deletion races.
- Gateway tests prove elapsed deadlines deny new traffic without a sweeper and
  close HTTP, SSE, and WebSocket streams at the known deadline.
- Database constraints admit only the three supported durations and one Agent-port
  service.
- Public projections and Agent results contain no request, approval, cycle,
  provenance, or historical exposure fields.

### webservice-260915/ADR-D2. Use a 12-character random row-lifetime hostname key

**Authority:** revised `webservice-260915/REQ-2`, `REQ-4`, `REQ-9`, and the
existing rule that a Runtime Web hostname is routing identity rather than an
authentication credential.

Each new service receives 60 bits from the platform cryptographic random source,
encoded as exactly 12 lowercase unpadded RFC 4648 Base32 characters. The stored
key remains unchanged for the lifetime of the service row, including label,
duration, On/Off, expiration, reset, Runtime restart, and Runtime generation
changes.

The hostname key has a database unique constraint. If insertion conflicts with a
different service, the repository discards that candidate and performs a bounded
regeneration attempt within the create operation. Exhausting the bound fails the
creation without changing any existing service. Random suffixes are not appended
to an already published key, and a collision never aliases or replaces another
service.

Deleting the service removes its hostname identity and dependent authentication
bootstrap records. Permanent Agent Runtime cleanup does the same. A later service
for the same Agent and port receives a newly generated key and URL. The hostname
remains non-secret: every request still requires the existing Gateway identity,
current user authorization, current service On state, and current Runtime
admission checks.

This decision supersedes the incidental `deterministic hostname key` descriptor in
ADR-D1 after the requester revised and reconfirmed REQ-2. It does not change
ADR-D1's accepted single-row service and exposure authority.

**Consequences**

- The hostname key is 12 characters instead of the current 32-character random key
  or a 26-to-52-character deterministic hash encoding.
- Service deletion has a complete identity boundary: recreation intentionally
  obtains a different URL.
- Collision handling is an ordinary internal retry rather than a stable-address
  invariant failure.
- Agent IDs, ports, installation secrets, and hash-version inputs are not encoded
  into the public hostname.

**Rejected alternatives**

- Deterministic truncated hashing: preserves addresses after deletion but requires
  a longer collision-resistant value and fail-closed collision policy, contrary to
  revised REQ-2.
- Reversible Agent-ID-and-port encoding: prevents collisions but exposes internal
  identifiers and requires 29 characters.
- Mixed-case Base62: DNS host labels are case-insensitive and therefore cannot
  preserve the encoding's intended identity space.

**Required evidence**

- Generation tests use an injected random source to verify exact lowercase Base32
  length and deterministic collision fixtures.
- Repository tests prove a uniqueness conflict retries without changing the
  existing service and bounded exhaustion returns no partial service.
- Delete and Runtime-removal tests prove dependent hostname bootstrap state is
  absent, and recreation produces a different URL.
- Gateway tests prove possession or guessing of a hostname alone grants no access.

### webservice-260915/ADR-D4. Delete legacy Session-scoped services at cutover

**Authority:** requester direction on 2026-09-15, `webservice-260915/REQ-1`
through `REQ-5`, `REQ-8`, and the revised row-lifetime identity in `REQ-2`.

The database migration deletes every legacy Session-scoped Runtime Web endpoint and
all endpoint-dependent request, cycle, operation-receipt, authentication binding,
and authentication ticket state. It does not merge endpoints that share an Agent
and port, select one Session label or approval as a winner, convert an active cycle
into an On service, retain tombstones, or create an old-to-new URL mapping.

The replacement Agent-port service table begins empty. A user create action or an
Agent request creates the first new service row and 12-character hostname. Every
legacy random hostname stops resolving after cutover. Global Runtime Web
authentication configuration and user Gateway identities remain only where they
are independent of a deleted endpoint; transport route authority remains governed
by its existing Runtime and generation lifecycle.

Public API, generated clients, TRPC, Agent tools, trusted activation UI, Gateway
authority, and Runtime Web stream authority switch to the new contract without
legacy route aliases, dual reads, dual writes, compatibility adapters, or fallback.
The deployment uses a maintenance cutover that drains old Gateway and Runtime Web
transport processes before the destructive schema boundary, then starts only
components that understand the new schema and exact protocol fingerprint.

**Consequences**

- Existing service URLs, pending approvals, active exposure windows, and service
  labels are intentionally discarded.
- No ambiguous cross-Session merge policy or approval-to-On conversion becomes
  hidden product behavior.
- Rollback across the destructive migration requires restoring the pre-cutover
  database and complete old deployment together; application rollback alone is not
  supported.
- Users and Agents recreate only the services still needed under the simpler
  management model.

**Rejected alternatives**

- Merge by Agent and port while selecting an oldest, newest, active, or labeled
  Session endpoint: every winner policy invents unauthorized behavior and still
  cannot preserve all legacy URLs.
- Preserve legacy hostname aliases or compatibility reads: retains Session-scoped
  identity and a second authority after the approved replacement.
- Convert active cycles into On services: silently carries approval-era state and
  expiration semantics into a model that explicitly removes them.

**Required evidence**

- Migration tests seed multiple Session endpoints for the same Agent and port,
  including pending and active state, and prove none remains after upgrade.
- Schema and generated-contract checks prove request/cycle tables and legacy API,
  tool, and stream fields have no reachable reader or writer.
- Cutover validation proves old hostnames fail closed and a newly created service
  receives an unrelated 12-character hostname.
- Deployment documentation identifies the drain, migration, new-component start,
  and database-restore rollback boundary.

### webservice-260915/ADR-D3. Create by port and mutate the exact service ID

**Authority:** `webservice-260915/REQ-1`, `REQ-2`, `REQ-4` through `REQ-8`,
ADR-D1, and ADR-D2.

Agent and user creation operations address the logical slot by authorized Agent and
numeric port. The Agent `request` input remains a port with an optional label, and
the user create contract carries the port, label, selected duration, and whether
to turn the new service On. An Agent label is a creation hint only: requesting an
existing port returns that service without changing its label, selected duration,
On/Off state, or expiration.

Every created row has a separate opaque service ID that lasts only for that row.
List and request results include the service ID and public URL. Mutations of an
existing row use that service ID. Human label, duration, On, Off, reset, and delete
mutations also carry the displayed service revision. Agent `close` accepts the
service ID, locks that exact row, turns it Off when On, and succeeds unchanged when
the row is already effectively Off. It cannot resolve a replacement row by port.

State-changing calls retain durable operation idempotency scoped to the authorized
actor, execution, operation kind, and client operation key. A receipt binds the
first execution to the exact service ID and input fingerprint, so retry cannot
repeat expiration reset or cross into a replacement service. Reusing a key with
different input fails. Receipts are technical retry state, are not exposed as
service history or creation provenance, and never grant authorization.

A missing service ID returns the normal private not-found result for read and
non-delete mutation. Human delete is idempotent at the authorized Agent route:
after Agent access is established, deleting a missing opaque ID succeeds without
revealing whether it previously existed. A stale ID never falls back to
`Agent + port`.

**Consequences**

- Delete and recreate produces a new hostname and service ID; stale UI, Agent, or
  network mutations cannot affect the replacement.
- Agent close may require a list call when the Agent no longer has the service ID
  from its request result.
- Port remains the user-understandable uniqueness and creation coordinate without
  becoming an unsafe long-lived mutation address.
- Trusted URL activation can continue using the same opaque row identity already
  needed by authentication bootstrap.

**Rejected alternative**

- Address every mutation by Agent and port: simpler call input, but a delayed
  mutation can cross the deletion boundary and affect a newly created row unless
  the system retains permanent port tombstones or a more complex historical
  receipt authority.

**Required evidence**

- API and Agent tool tests prove creation/request by port and every existing-row
  mutation by service ID.
- A delayed stale mutation against a deleted ID cannot affect a newly created
  service on the same port.
- Idempotency tests prove exact retry, mismatched-key rejection, reset
  non-extension, and receipt non-authorization.
- Agent request tests prove an existing user label, duration, state, and expiration
  remain unchanged; Agent close tests prove On-to-Off and already-Off success.

## Decision Ownership

The requester confirmed `webservice-260915/REQ` on 2026-09-15 and retains ownership
of unresolved material technical decisions. Local identifiers, helper boundaries,
file placement, component composition, fixtures, and equivalent implementation
details remain Agent-owned after the material decisions are accepted.
