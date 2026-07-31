---
title: "Reliable External Channel Provider Connections"
created: 2026-07-31
tags: [architecture, external-channel, slack, discord, reliability]
document_role: primary
document_type: adr
snapshot_id: channel-260731
---

# channel-260731/ADR: Reliable External Channel Provider Connections

## Context

The confirmed
[channel-260731/REQ](../requirements/channel-260731-reliable-provider-connections.md)
requires Slack and Discord transports to recover through provider-conformant connection
lifecycle behavior while preserving durable admission-before-acknowledgement,
multi-replica ownership fencing, sanitized terminal health, and existing External
Channel product behavior.

The current implementation already uses `discord.py` and `slack-sdk`, but it retains
several parallel transport owners:

- Discord calls `Client.start(reconnect=True)` while also classifying SDK termination,
  running a second reconnect/backoff loop, and mutating private process-global Discord
  REST and Gateway endpoints.
- Slack disables Socket Mode automatic reconnect, discards the SDK message dispatcher,
  mints every endpoint outside the Socket client, and owns a separate reconnect and
  stale-session watchdog.
- Slack HTTP reimplements the request-signature algorithm already supplied by the SDK.
- Discord lease gaps are recorded but never cleared by typed SDK ready or resumed
  callbacks. Slack marks a Socket connection active before the WebSocket has connected.
- The Agent Worker does not fail when its top-level Slack Socket manager task exits
  unexpectedly, so Kubernetes readiness can remain successful after transport
  supervision has stopped.

The durable connection lease, configuration and App-claim generations, provider-history
ingestion, authorization, acknowledgement ordering, and content-free evidence remain
Azents domain responsibilities. Provider frame parsing, heartbeat, endpoint renewal,
reconnect, and Resume do not.

## Decision Backlog

1. **Accepted: provider SDK ownership of in-process transport lifecycle.**
2. **Accepted: Azents ownership of durable admission, terminal classification, and
   distributed fencing.**
3. **Accepted: typed lifecycle observation drives durable health and worker
   supervision.**
4. **Accepted: private endpoint mutation is isolated to deterministic tests.**

## Decisions

### channel-260731/ADR-D1 — Provider SDKs own connection mechanics

`discord.py` owns Gateway discovery, Identify, heartbeat, reconnect, and in-process
Resume through one `Client.start(reconnect=True)` lifecycle per current lease.
Azents does not retry an SDK-declared non-recoverable close through a second connection
loop.

The Slack aiohttp `SocketModeClient` runs with automatic reconnect enabled and owns
`apps.connections.open`, WebSocket establishment, Ping/Pong, stale detection, close
recovery, refresh requests, and endpoint replacement. Azents does not discard the SDK
queue, mint each endpoint separately, run a competing watchdog, or recreate the
connection after each recoverable outcome.

The SDK queue dispatcher is not the admission boundary because it schedules listeners
independently and swallows their exceptions. The SDK direct receive callback instead
provides the serial, awaitable boundary required for durable
admission-before-acknowledgement. The SDK queue remains enabled for its own control
messages but has no Azents event listener.

This decision applies to `channel-260731/REQ-1` and `REQ-5`.

### channel-260731/ADR-D2 — Azents retains only durable and security-critical ownership

Azents retains:

- connection lease, configuration-generation, App-claim-generation, and lease-generation
  fencing;
- provider identity, transport, and credential authorization;
- bounded callback projection and provider-history authority;
- synchronous durable admission before Slack acknowledgement;
- exact SDK acknowledgement construction and transmission after admission;
- terminal credential, intent, authorization, and insecure-endpoint classification;
- cancellation of an SDK lifecycle immediately after lease loss or shutdown; and
- content-free reason codes and evidence.

For Slack, a thin SDK subclass may observe endpoint acquisition and reconnect entry so
terminal SDK errors can be surfaced to the lease owner and durable gap/active state can
be recorded. It must call the SDK implementation rather than reproduce endpoint,
WebSocket, heartbeat, or reconnect behavior.

Slack HTTP uses the SDK `SignatureVerifier`. Azents still selects the candidate
connection from bounded untrusted App/Team identity before verification because each
Workspace-owned Slack App has a different signing secret.

This decision applies to `channel-260731/REQ-2`, `REQ-3`, and `REQ-4`.

### channel-260731/ADR-D3 — Typed lifecycle events are the health authority

Discord `on_disconnect`, `on_ready`, and `on_resumed` callbacks update the current
fenced lease. Disconnect records a degraded gap. Ready or resumed marks the connection
active and clears the current gap. A stale callback cannot mutate a newer lease.

Slack records a degraded gap when the SDK begins endpoint replacement and marks the
connection active only after the SDK reports a successfully established session.

Provider-specific connection health remains per connection. Kubernetes readiness does
not fail merely because one customer configuration needs reconnection. It does fail
indirectly when a required top-level transport manager exits: the owning process
propagates that failure and terminates instead of continuing to report ready.

This decision applies to `channel-260731/REQ-1`, `REQ-2`, and `REQ-6`.

### channel-260731/ADR-D4 — Production endpoint selection remains SDK-owned

Production Discord REST and Gateway endpoint selection is never changed through private
SDK globals. Deterministic provider fakes may use one explicit test-only context that
temporarily applies and then restores the SDK endpoint state because `discord.py` has no
public Gateway endpoint injection boundary.

Slack production accepts only SDK-issued secure WebSocket endpoints. An insecure
endpoint remains available only when the existing explicit deterministic-test
configuration is enabled.

This decision applies to `channel-260731/REQ-5` and `REQ-7`.

## Consequences

- Recoverable provider transitions stay inside one SDK lifecycle and one Azents lease.
- Durable health follows typed provider lifecycle evidence rather than task existence.
- Slack event admission remains serialized and acknowledgement remains after durable
  completion even though the SDK owns reconnect.
- Terminal errors require a small observation adapter because the Slack SDK reconnect
  loop does not expose them as a stable lifecycle result.
- Existing public APIs, routing, authorization, provider-history, Session, delivery,
  and file-transfer behavior do not change.
- Deterministic tests retain a private Discord seam, but production code paths do not
  mutate private SDK endpoint state.

## Rejected Alternatives

- **Keep all current manager loops:** rejected because they continue to duplicate and
  override maintained SDK lifecycle behavior.
- **Delegate Slack admission to the SDK dispatcher or Bolt:** rejected because listener
  tasks are independently scheduled and failures are swallowed, which cannot enforce
  serial durable admission-before-acknowledgement or lease-loss propagation.
- **Remove Slack Socket Mode:** rejected because it is an existing supported transport
  and removal is outside the confirmed Requirements.
- **Make Pod readiness depend on every customer connection:** rejected because one
  invalid customer configuration must not remove a healthy shared worker from service.
- **Persist provider Resume/session state:** rejected because the SDK owns in-process
  session recovery and cross-process provider session state is not Azents authority.

## Risks

- SDK lifecycle methods are not all formal protocol interfaces. Focused compatibility
  tests must detect future SDK behavior changes.
- Slack automatic reconnect can encounter terminal token errors inside an SDK loop.
  The observation adapter must surface only bounded error categories and cancel that
  loop without logging provider responses.
- Concurrent SDK lifecycle callbacks can arrive near message admission. Repository
  generation fencing and callback serialization must prevent stale health or admission.
