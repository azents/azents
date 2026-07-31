---
title: "Reliable External Channel Provider Connections Design"
created: 2026-07-31
updated: 2026-07-31
implemented: 2026-07-31
tags: [external-channel, slack, discord, reliability]
document_role: primary
document_type: design
snapshot_id: channel-260731
---

# channel-260731/DESIGN: Reliable External Channel Provider Connections

## Requirements and Decisions

This design implements
[channel-260731/REQ](../requirements/channel-260731-reliable-provider-connections.md)
under [channel-260731/ADR](../adr/channel-260731-reliable-provider-connections.md).

The implementation changes transport ownership only. External Channel App management,
route selection, access policy, provider-history sourcing, binding, invocation,
Session, Channel Work, provider delivery, and file transfer retain their current
contracts.

## Discord Gateway

### SDK client boundary

`_DiscordLibraryClient` continues to request only Guild, Guild Messages, and Message
Content intents and to emit typed `discord.Message` callbacks.

Add a typed lifecycle callback with these states:

- `disconnected`;
- `ready`; and
- `resumed`.

`on_disconnect`, `on_ready`, and `on_resumed` emit those states through the same
serialized callback boundary used by message admission. Callback failure closes the
SDK client and is surfaced to the lease manager. Message and lifecycle callbacks do not
read raw Gateway payloads, session IDs, sequence numbers, Resume URLs, or private cache
state.

`DiscordGatewayClient` creates one client and awaits
`Client.start(token, reconnect=True)`. Recoverable transport failures remain inside
that call. Login failure and privileged-intent failure keep dedicated sanitized
exceptions. Any other SDK-declared non-recoverable close becomes one sanitized terminal
Gateway error rather than entering an Azents reconnect loop.

Production does not assign `discord.http.Route.BASE` or
`DiscordWebSocket.DEFAULT_GATEWAY`. When explicit deterministic test endpoint
environment variables are present, one context manager applies the test endpoints for
the lifetime of the test client and restores the prior globals afterward.

### Lease manager and health

The manager claims and renews the existing generation-fenced ingress lease. It starts
one SDK lifecycle and cancels it immediately on shutdown or failed renewal.

Lifecycle handling is fenced by connection ID, manager owner, and lease generation:

- `disconnected` atomically moves the connection to `degraded`, records the bounded
  gap reason, and refreshes lease heartbeat;
- `ready` or `resumed` atomically moves the connection to `active`, clears the current
  gap, and refreshes lease heartbeat; and
- stale lifecycle callbacks raise lease-lost and close the client.

The manager removes its outer reconnect-attempt count, exponential delay, rate-limit
delay, and `DiscordGatewayConnectionResult`. A terminal SDK exception moves the current
connection to `reconnect_required`; cancellation or lease loss only releases current
ownership.

## Slack Socket Mode

### SDK client boundary

Replace `AzentsSlackSocketModeClient.enqueue_message()` with a thin observed
`SocketModeClient` subclass that leaves SDK message queuing intact and enables automatic
reconnect.

The subclass:

- delegates endpoint acquisition to `super().issue_new_wss_url()`;
- validates the returned endpoint as secure, except for the existing explicit
  deterministic-test boundary;
- reports transient endpoint failures as degraded gaps while the SDK keeps retrying;
- reports a bounded terminal credential category before re-raising the SDK error so
  the runner can cancel the otherwise unbounded SDK retry loop;
- reports reconnect entry before `super().connect_to_new_endpoint()`; and
- reports active only after `super().connect()` successfully establishes the session.

It does not implement WebSocket I/O, Ping/Pong, stale detection, endpoint renewal,
reconnect locking, delay, or frame receipt.

The direct SDK `on_message` callback remains the admission boundary. It bounds and
parses text through `SocketModeRequest`, awaits event or interaction admission, sends
`SocketModeResponse` only afterward, and schedules transient interaction provider work
only after acknowledgement. Admission failure completes the runner with an exception
and leaves the envelope unacknowledged.

The SDK queue has no Azents message or request listeners. It remains enabled so the SDK
can process `disconnect` control messages and own endpoint refresh. Recoverable close,
error, stale, and refresh behavior no longer completes the Azents runner.

### Lease manager and health

The manager creates one Socket Mode runner per claimed connection and lets it run until
shutdown, lease loss, admission failure, or a terminal SDK outcome.

Lifecycle callbacks call existing fenced repository operations:

- reconnect entry records a degraded gap;
- successful connection marks active and clears the gap; and
- terminal credential outcome releases ownership and moves the connection to
  `reconnect_required`.

Remove `SlackSocketWebAPIClient`, manager-owned endpoint minting, the manager reconnect
loop, the transport watchdog, and the pre-connect active transition.

## Slack HTTP

Replace the custom HMAC implementation in `verify_slack_signature` with
`slack_sdk.signature.SignatureVerifier`.

An injected SDK `Clock` adapter returns the supplied timezone-aware request timestamp so
tests and replay-window behavior remain deterministic. Missing or malformed headers,
invalid UTF-8, invalid timestamps, stale timestamps, and signature mismatch map to the
existing `SlackHTTPUnauthorized` boundary without exposing input values.

Candidate App/Team extraction, connection lookup, credential decryption, bounded JSON
or form parsing, callback projection, durable admission, and response timing remain
Azents-owned.

## Worker Supervision and Readiness

The Discord Gateway process already awaits the manager as its foreground task, so an
unexpected manager exit terminates the process.

The Agent Worker must include the Slack Socket manager task in its main wait boundary.
If the task raises or returns before shutdown, the Worker raises and exits. Its health
server can therefore no longer continue returning readiness after Socket supervision
has stopped. Customer connection errors remain durable per-connection health and do not
make the shared Worker unready.

No public health response includes connection identifiers, provider endpoints, payload
content, or credentials.

## Repository Changes

Add one fenced Discord transition that updates the connection and ingress lease
together:

- degraded transition: connection `status=degraded`, lease gap timestamp/reason and
  heartbeat set;
- active transition: connection `status=active`, lease gap timestamp/reason cleared and
  heartbeat set.

The transition requires the current lease owner, lease generation, configuration
generation, App-claim generation, and unexpired lease through the existing fence.

Slack continues using `record_socket_connection_gap` and
`mark_socket_connection_active`, which already fence by owner and lease expiry.

No schema or public API change is required.

## Failure Handling

| Failure | Outcome |
| --- | --- |
| Discord recoverable network/Gateway transition | `discord.py` reconnects or resumes; fenced gap then active lifecycle projection |
| Discord login or intent rejection | fenced `reconnect_required` |
| Discord SDK-declared non-recoverable close | fenced `reconnect_required` with bounded reason |
| Slack recoverable close, stale session, or refresh | SDK endpoint replacement; fenced gap then active lifecycle projection |
| Slack terminal App-token error | runner cancels SDK loop; fenced `reconnect_required` |
| Slack event or interaction admission failure | no acknowledgement; runner fails so provider redelivery can recover |
| Lease loss or configuration replacement | SDK client is canceled and closed; stale callback cannot mutate |
| Top-level Slack manager failure | Agent Worker exits instead of remaining ready |

Cancellation is always caught separately and re-raised. Logs contain only operation,
provider, transport, lifecycle state, bounded reason code, and exception class where
needed. Provider IDs, endpoint URLs, response bodies, callback payloads, message
content, and credentials are excluded.

## Living Spec Updates

Update:

- `docs/azents/spec/domain/external-channel.md`;
- `docs/azents/spec/flow/external-channel-provider-ingress.md`; and
- `docs/azents/spec/flow/external-channel-lifecycle.md`.

The specs must state that both provider SDKs own recoverable connection lifecycle,
typed lifecycle callbacks drive fenced health, Slack direct receive callbacks preserve
durable acknowledgement ordering, and top-level manager failure terminates its worker.

## Test Strategy

### E2E-first scenarios

Extend deterministic provider fakes and External Channel E2E to prove:

1. Discord initial READY marks active and clears an earlier gap.
2. Discord recoverable disconnect reconnects or resumes through `discord.py` without
   an Azents reconnect loop and continues message admission.
3. Discord terminal credential or intent failure becomes `reconnect_required`.
4. Slack Socket initial active state occurs only after WebSocket establishment.
5. Slack refresh, close, and stale recovery issue a replacement endpoint through the
   SDK and continue durable admission.
6. Slack retryable admission sends no acknowledgement before SDK recovery.
7. Slack terminal App-token failure becomes `reconnect_required`.
8. Lease loss cancels either SDK lifecycle and prevents stale health or admission.
9. A failed Slack Socket manager terminates the Agent Worker supervision path.
10. Evidence remains content-free.

### Focused coverage

Add or update tests for:

- Discord typed lifecycle callback serialization and callback-failure closure;
- production endpoint globals remaining untouched and test endpoint restoration;
- removal of Discord outer reconnect decisions and delays;
- fenced Discord degraded/active repository transitions;
- Slack automatic reconnect enabled with the SDK queue intact;
- endpoint security and terminal error observation around the SDK implementation;
- SDK reconnect entry and connected callbacks;
- durable ACK ordering through direct message callbacks;
- removal of the custom Slack watchdog and endpoint-open client;
- SDK `SignatureVerifier` replay, malformed-header, and signature behavior; and
- Agent Worker manager-task failure propagation.

Run Python format, Ruff, Pyright, focused and full pytest, deterministic External
Channel E2E, documentation checks, and Helm rendering tests. OpenAPI and generated
clients require verification but no regeneration unless implementation unexpectedly
changes a public contract.

## Feasibility

| Requirement | Result | Evidence |
| --- | --- | --- |
| `REQ-1` | feasible | Both installed SDKs already implement reconnect and heartbeat; current clients expose typed callbacks or overridable lifecycle methods. |
| `REQ-2` | feasible | Existing repository methods already terminalize fenced credential and intent failures. |
| `REQ-3` | feasible | Slack direct receive callbacks already await durable admission before `SocketModeResponse`. |
| `REQ-4` | feasible | Existing Slack and Discord lease fences guard admission, renewal, gap, release, and terminal transitions. |
| `REQ-5` | feasible | Current duplicate loops can be removed while retaining thin observation and test seams. |
| `REQ-6` | feasible | Existing health server follows process lifecycle; only Slack manager task failure propagation is missing. |
| `REQ-7` | feasible | Deterministic Slack and Discord fakes already model disconnect, endpoint, heartbeat, READY, and Resume behavior. |

No implementation blocker remains.
