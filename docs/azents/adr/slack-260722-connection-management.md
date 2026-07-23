---
title: "Slack Connection Setup and Management"
created: 2026-07-22
tags: [slack, external-channel, frontend, security, operations, architecture]
document_role: primary
document_type: adr
snapshot_id: slack-260722
---

# Slack Connection Setup and Management

- Snapshot: `slack-260722`
- Document reference: `slack-260722/ADR`
- Requirements: [Slack Connection Setup and Management Requirements](../requirements/slack-260722-connection-management.md) (`slack-260722/REQ`)

## Status

Accepted.

## Context

The initial External Channel management implementation uses an opaque HTTP callback
selector to find a connection before verifying its Slack signature. Setup returns the
selector once, but the Web UI discards it and displays only a path template. The
resulting Slack App cannot be completed from the product UI.

The same management surface treats disconnected connections as terminal UI rows:
disconnect is disabled, reconnect replaces only credential fields, and App identity
cannot be corrected. The requester requires every connection to be removable without
a lifecycle guard and requires a complete first-time setup experience.

## System-Grounded Framing

- Slack `event_callback` envelopes parsed by Azents already require `api_app_id` and
  `team_id`.
- Slack App ID plus Team ID identifies the connection candidate whose encrypted
  Signing Secret verifies the raw request.
- URL-verification envelopes require only a bounded challenge response and do not
  admit an event or invoke an Agent.
- The connection row is referenced by retained provider events, resources, and
  history through restrictive foreign keys. Physical deletion would either destroy
  history or require broad ownership migration.
- Connection disconnect already terminalizes routes, bindings, Channel Work, pending
  context, and credentials while preserving provider and Session history.
- The management list currently includes disconnected rows even though they no longer
  represent usable connections.
- A fixed callback URL allows a complete Slack App Manifest to be generated before
  credentials or a connection record exist.

## Feasibility

The stable callback is feasible. Ordinary event routing uses the payload identity only
to select a candidate; successful HMAC verification with the selected connection's
Signing Secret is still required before durable admission. An attacker cannot admit
an event by supplying another App or Team identity without the matching secret.

URL verification is handled as a bounded, side-effect-free protocol acknowledgement.
It does not select a connection, authenticate an Azents user, create a record, or
permit an ordinary event.

## Decisions

### slack-260722/ADR-D1 — Use one fixed Slack HTTP callback

Azents uses:

```text
POST /external-channel/v1/slack/events
```

HTTP event callbacks are routed by `(api_app_id, team_id)`, then verified against the
candidate connection's Signing Secret before parsing and durable admission.

URL verification parses only a bounded JSON challenge and returns it without
connection lookup or durable side effects.

Per-connection selector generation, selector hashing, selector route parameters, and
selector setup guidance are removed.

**Rejected**

- Retain selectors and fix only the UI. This keeps an unnecessary capability URL,
  complicates Manifest generation, and leaves selector-loss recovery.
- Route by App ID alone. One Slack App may have multiple installations; Team ID is
  required to select an installation.

### slack-260722/ADR-D2 — Disconnect is unguarded, idempotent, and removed from management

The management disconnect command accepts every connection status. It always
terminalizes the route and owned live state, clears credentials, and returns the
terminal projection. Repeating it returns the same terminal projection.

Disconnected connections are omitted from the active Agent connection list. Their
rows remain as retained provider-history roots because restrictive references and
historical Session presentation require stable identity.

**Rejected**

- Physically delete the connection graph. This would conflict with retained event and
  conversation history.
- Keep disconnected rows in the active management list. This creates an
  unremovable-card experience and does not represent an actionable integration.

### slack-260722/ADR-D3 — Edit replaces complete Slack setup and revalidates

One update operation replaces App ID, transport, and the submitted transport-specific
credential set. It never reads existing secrets back to the browser. The connection
enters configuring state and is immediately validated with Slack.

Every visible connection state is editable. UI action locking may prevent concurrent
submissions, but lifecycle state does not disable edit or disconnect.

**Rejected**

- Credential-only reconnect. It cannot correct an App ID or transport mistake.
- Partial secret patching. The browser cannot distinguish an omitted secret from a
  retained hidden value safely enough for a clear first-time recovery flow.

### slack-260722/ADR-D4 — Provide generated Manifest and manual Slack UI guides

The setup surface presents two first-class paths:

1. a JSON App Manifest generated from the Agent/App display name and fixed callback
   URL; and
2. a step-by-step manual Slack UI path using the same scopes, events, and callback.

Both paths identify where App ID, Bot User OAuth Token, and Signing Secret are copied
and explain that App-Level Token is required only for Socket Mode.

### slack-260722/ADR-D5 — Home exposes an exact public operation

Home's public Gateway accepts only HTTPS `POST` on the exact fixed callback path.
Path prefixes, descendants, HTTP, health, management, Web, and Admin routes are not
publicly routed.

## Consequences

- Existing selector callback URLs stop working after deployment and Slack Apps must
  use the fixed callback URL. No legacy fallback is retained.
- Existing disconnected rows disappear from active management without deleting
  retained history.
- Setup can provide a complete Manifest before connection creation.
- HTTP admission performs a bounded pre-authentication identity parse before HMAC
  verification; the parsed fields are not trusted until verification succeeds.
- Home and Azents changes must be coordinated so the exact fixed callback becomes
  reachable when the new server route is deployed.
