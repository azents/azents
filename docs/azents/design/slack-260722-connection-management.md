---
title: "Slack Connection Setup and Management Design"
created: 2026-07-22
updated: 2026-07-22
tags: [slack, external-channel, frontend, security, operations, testing]
document_role: primary
document_type: design
snapshot_id: slack-260722
---

# Slack Connection Setup and Management Design

- Snapshot: `slack-260722`
- Document reference: `slack-260722/DESIGN`
- Requirements: [Slack Connection Setup and Management Requirements](../requirements/slack-260722-connection-management.md) (`slack-260722/REQ`)
- ADR: [Slack Connection Setup and Management](../adr/slack-260722-connection-management.md) (`slack-260722/ADR`)

## Overview

This change replaces selector-based Slack HTTP callbacks with one fixed endpoint,
makes disconnect unconditional and idempotent, replaces credential-only reconnect
with complete connection editing, and turns the setup modal into a guided flow for
both Manifest and manual Slack App creation.

Connection rows remain durable history roots. Disconnect immediately removes the
connection from active management by terminalizing it and filtering terminal rows
from the active list; it does not erase imported messages or AgentSession history.

## Traceability

| Requirement | ADR decisions | Design mechanism |
| --- | --- | --- |
| `slack-260722/REQ-1` | `slack-260722/ADR-D2` | Unguarded idempotent disconnect and active-list filtering |
| `slack-260722/REQ-2` | `slack-260722/ADR-D3` | Complete Slack connection update and immediate validation |
| `slack-260722/REQ-3` | `slack-260722/ADR-D4` | Manifest and manual Slack UI guide tabs/sections |
| `slack-260722/REQ-4` | `slack-260722/ADR-D1`, `slack-260722/ADR-D4` | Server-owned Manifest object and copy action |
| `slack-260722/REQ-5` | `slack-260722/ADR-D1` | Payload identity lookup followed by HMAC verification |
| `slack-260722/REQ-6` | `slack-260722/ADR-D5` | Exact-method, exact-path Home HTTPRoute |

## Current Behavior and Gaps

- `POST /slack/events/{selector}` hashes the selector and looks up one connection.
- Connection creation returns the raw selector once, but the Web container closes the
  dialog and discards the response.
- Manifest guidance returns lists and a callback path template instead of a valid App
  Manifest.
- `switch_transport` and `replace_credentials` reject disconnected connections.
- The Web row disables disconnect and transport changes for terminal connections.
- Connection list queries return disconnected connections indefinitely.
- Reconnect does not accept App ID or transport replacement.
- Home exposes a callback path prefix rather than one exact operation.

## Backend Design

### Fixed callback admission

The callback route becomes:

```text
POST /external-channel/v1/slack/events
```

Admission executes in this order:

1. reject a body larger than the existing Slack HTTP limit;
2. parse a small routing envelope containing callback type and, for ordinary events,
   `api_app_id` and `team_id`;
3. for `url_verification`, return the bounded challenge without persistence;
4. for `event_callback`, query one HTTP Slack connection by provider App and tenant
   identity;
5. require encrypted Slack credentials and an active/degraded connection;
6. verify Slack timestamp and raw-body HMAC with the selected Signing Secret;
7. run the existing full projection parser;
8. re-check that the verified parsed identity equals the selected connection; and
9. durably admit through the existing idempotent admission service.

The routing parser treats payload identity as an index key, not authentication. HMAC
verification remains the authentication boundary.

The repository gains a lookup by `(provider, transport, provider_app_id,
provider_tenant_id)` restricted to callback-eligible status. Selector lookup and
hashing are removed from runtime code and schema writes. The existing nullable
selector column may remain temporarily unused to avoid rewriting an executed
migration; a later cleanup migration may drop it.

### Manifest guidance

The authenticated guidance endpoint accepts an optional requested App display name
or derives a safe default from the Agent. Its response contains:

- `callback_url`;
- structured Manifest JSON;
- pretty-printed `manifest_json`;
- required Bot scopes;
- required Bot events;
- credential-location guidance identifiers; and
- Socket Mode requirements when explicitly selected.

The HTTP callback URL comes from server public configuration and is always complete.
No secret is included in the Manifest.

### Complete connection update

The credential-only reconnect endpoint is replaced or extended with a request
containing:

- `app_id`;
- `transport`;
- `credentials.bot_token`;
- `credentials.signing_secret`; and
- nullable `credentials.app_token`.

The service authorizes Agent administration, validates the provider contract,
encrypts the replacement set, updates App identity and transport, clears stale
provider identity/capability/health fields, sets configuring state, and performs the
existing Slack validation. Validation uses `auth.test` for Team/Bot identity and
`bots.info` for the Bot's actual App ID, then requires that App ID to match the
submitted value. A valid result writes Team/Bot identity and active state.

No lifecycle-state guard prevents editing a visible connection. Ownership,
credential-shape validation, and the Socket Mode App Token requirement remain.

### Unguarded disconnect

`begin_connection_disconnect` no longer short-circuits into a forbidden or separate
terminal path. If already disconnected, it returns no cleanup work. Otherwise it
terminalizes active owned state as today.

`complete_connection_disconnect` always clears credentials, route availability, and
lease fields and writes disconnected state. The command remains safe when repeated.

`list_connections` excludes disconnected rows. Historical views continue joining the
retained connection identity.

## Web Design

### Setup dialog

The dialog uses a guided sequence:

1. **Choose creation method**
   - "Create with Manifest (recommended)"
   - "Create manually in Slack"
2. **Create and install the Slack App**
   - Manifest path shows copy-ready JSON and exact Slack menu sequence.
   - Manual path lists Bot User, OAuth scopes, Event Subscriptions, fixed Request URL,
     Workspace installation, and channel invitation steps.
3. **Copy values from Slack**
   - App ID: Basic Information → App Credentials.
   - Signing Secret: Basic Information → App Credentials.
   - Bot Token: OAuth & Permissions → OAuth Tokens for Your Workspace.
   - App Token: Basic Information → App-Level Tokens, shown only for Socket Mode.
4. **Save and validate**

The UI explains `xoxb-` versus `xapp-`, warns not to share credentials, and uses a
copy button for both Callback URL and Manifest JSON.

### Connection row

- Disconnect remains enabled for every visible state unless another mutation for the
  same row is currently running.
- "Edit connection" opens the same credential form populated with non-secret App ID
  and transport values; secret fields are blank and required for save.
- Validation remains an explicit health action.
- The UI contains no lifecycle-derived `terminal` guard for edit or disconnect.

## API and Client Impact

- Replace the selector callback route with the fixed callback route.
- Expand Manifest guidance response with callback URL and Manifest JSON.
- Add complete connection update request/operation.
- Keep disconnect as `DELETE` but make it idempotent and omit disconnected rows from
  active list responses.
- Regenerate OpenAPI, Python public client, and TypeScript public client.
- Update the tRPC router to use generated client operations only.

## Home Design

The Home `HTTPRoute` matches:

- hostname `azents.hardtack.me`;
- HTTPS listener;
- method `POST`; and
- exact path `/external-channel/v1/slack/events`.

It forwards to `Service/apiserver:8010`. No prefix match is retained.

## Migration and Rollout

- No executed migration is edited.
- Existing selector hashes become unused.
- Existing HTTP Slack Apps must replace their Request URL with the fixed URL.
- Existing disconnected rows automatically disappear from active management after
  the server change.
- Deploy Azents and Home changes in a coordinated window. Either deployment order is
  safe for management routes, but Slack delivery transitions only after both the
  server route and Gateway route are available.
- Rollback requires restoring both the selector server route and prefix Gateway
  route; no compatibility fallback is included.

## Security and Failure Handling

- Payload App/Team identity is untrusted until HMAC verification succeeds.
- Candidate lookup returns no secret or identity detail to the caller.
- Unknown or ambiguous identity returns the same unauthorized response.
- URL verification accepts only bounded JSON and returns only the bounded challenge.
- Ordinary event admission never proceeds without signature verification.
- Disconnect commits terminal local state independently from provider cleanup outcome.
- Secret values remain write-only and redacted from logs, errors, API projections,
  stories, and tests.

## Test Strategy

### Backend

- URL verification succeeds on the fixed route without creating an event.
- Valid signed event routes by App/Team identity and admits once.
- Wrong App, Team, secret, timestamp, and malformed routing envelopes are rejected.
- Duplicate App/Team ambiguity fails closed.
- Selector route is absent from routing and OpenAPI.
- Disconnect succeeds from every connection status and succeeds when repeated.
- Disconnected rows are absent from active list while retained history still resolves.
- Complete edit replaces App ID/transport/credentials and validates.
- Socket edit requires App Token; HTTP edit does not.
- Manifest JSON contains fixed callback, scopes, events, and no secrets.

### Web

- Stories and component tests cover Manifest guide, manual guide, setup, edit,
  validation failure, and mutation-busy states.
- Disconnect and edit are enabled across all visible lifecycle states.
- Copy actions expose the complete callback URL and valid JSON Manifest.
- Secret inputs are blank in edit mode.

### E2E

- A first-time HTTP setup retrieves Manifest guidance, creates a connection, validates
  it, sends a signed event to the fixed route, and observes active management state.
- The connection is edited with a replacement App ID/credential fixture.
- Disconnect removes it from the active list and a repeated API disconnect remains
  successful.
- Public-route probes verify callback POST forwarding and 404 for callback GET,
  callback descendants, root, management, health, and plain HTTP.

### Quality and CI

- Run focused Ruff, Pyright, and Pytest for the Azents backend.
- Regenerate and validate public API clients.
- Run TypeScript format, lint, typecheck, and build sequentially.
- Run relevant deterministic E2E coverage.
- Validate Home Kustomize rendering and repository hooks.
- Create separate Azents and Home PRs and monitor all required CI checks.

## Feasibility Result

| Requirement | Result | Evidence |
| --- | --- | --- |
| `REQ-1` | Feasible | Existing disconnect transition is already idempotent at the repository boundary; list projection can exclude terminal rows. |
| `REQ-2` | Feasible | Existing encrypted credential replacement and Slack validation can be composed with App/transport replacement. |
| `REQ-3` | Feasible | The current setup modal and localized copy can host two explicit guide paths. |
| `REQ-4` | Feasible | The fixed callback removes the only dynamic placeholder; scopes/events already exist in guidance. |
| `REQ-5` | Feasible | Current parser requires `api_app_id` and `team_id`; HMAC remains authoritative. |
| `REQ-6` | Feasible | Gateway API supports exact path and HTTP method matching on the public HTTPS listener. |

No requirement-level or design-level blocker remains.
