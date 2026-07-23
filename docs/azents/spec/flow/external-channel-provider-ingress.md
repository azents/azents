---
title: "External Channel Provider Ingress"
created: 2026-07-22
tags: [backend, external-channel, slack, ingress, security]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation]
code_paths:
  - python/apps/azents/src/azents/api/public/external_channel/v1/route.py
  - python/apps/azents/src/azents/services/external_channel/admission.py
  - python/apps/azents/src/azents/services/external_channel/http_admission.py
  - python/apps/azents/src/azents/services/external_channel/slack_http.py
  - python/apps/azents/src/azents/services/external_channel/slack_socket.py
  - python/apps/azents/src/azents/services/external_channel/socket_manager.py
  - python/apps/azents/src/azents/services/external_channel/slack_events.py
  - python/apps/azents/src/azents/services/external_channel/event_processor.py
  - python/apps/azents/src/azents/services/external_channel/provider.py
  - python/apps/azents/src/azents/services/external_channel/slack_endpoint.py
  - python/apps/azents/src/azents/worker/worker.py
  - testenv/azents/e2e/src/support/slack_provider_fake.py
  - testenv/azents/e2e/src/tests/azents/public/test_external_channels.py
api_routes:
  - /external-channel/v1/slack/events
last_verified_at: 2026-07-23
spec_version: 4
---

# External Channel Provider Ingress

## Scope

The Slack adapter accepts only app-member public or private channel traffic. Slack Connect, DMs, group DMs, shortcuts, reactions, slash commands, and unrelated bot auto-triggers are outside the current scope. A tracked conversation is one Slack thread rooted by an eligible App mention and owned by a dedicated route whose Agent lifecycle is active.

## HTTP Admission

Slack sends HTTP callbacks to the single fixed endpoint
`POST /external-channel/v1/slack/events`.

1. The adapter reads a bounded raw body and parses only the minimum routing envelope.
2. A bounded `url_verification` request returns its challenge without connection
   lookup, durable admission, or Agent side effects.
3. An ordinary event uses untrusted `(api_app_id, team_id)` payload identity to select
   exactly one active or degraded HTTP connection.
4. The adapter validates Slack timestamp freshness and the raw-body HMAC signature
   against that candidate's encrypted Signing Secret.
5. The fully parsed event identity must match the selected connection before the raw
   provider event is persisted idempotently.
6. Success is acknowledged only after durable admission. Admission does not decrypt
   provider content into domain rows, hydrate history, authorize a participant,
   create an AgentSession, wake an Agent, or call a provider mutation API.

Payload App/Team identity is an index key, not authentication. Missing, unknown, or
ambiguous candidates fail closed, and ordinary events never pass admission without
successful HMAC verification.

Duplicate `(connection_id, provider_event_id)` callbacks reuse the admitted event and still receive a successful acknowledgement.

## Socket Mode Admission

A connection-selected Socket worker acquires a fenced lease before opening `apps.connections.open` with the app-level token. The WebSocket client admits Events API envelopes through the same durable admission service and sends the exact envelope acknowledgement only after admission returns. Failed admission remains unacknowledged.

Socket refresh/reconnect reasons are normalized. Invalid authentication moves the
connection to `reconnect_required` without changing its connection-to-Agent relationship. Socket-only gap
reasons are persisted for operators. Lease owner and expiry fence heartbeat, renew,
release, gap, and active-state writes. Shutdown and cancellation close the socket and
release ownership without exposing tokens.

Production permits only secure Slack endpoints. Test-only HTTP and insecure WebSocket overrides require explicit `AZ_TESTENV_SLACK_*` configuration.

## Asynchronous Processing

The worker claims admitted events in bounded batches with a claim owner and expiry. Processing is at-least-once and every canonical insert/update is idempotent.

- Provider health failures and token revocation update connection health without
  changing the configured connection-to-Agent relationship, bindings, or work.
- Every event-persistence and hydration-page transaction locks its `active` or
  `degraded` connection while selecting the active Agent route, then locks the
  active binding before the resource. This common connection→binding→resource
  order serializes disconnect before or after, never between, route admission and
  canonical writes.
- App uninstall terminalizes provider resources and credentials while preserving the
  connection-to-Agent relationship for later reconfiguration.
- Eligible invocation messages validate channel membership and Slack Connect/DM exclusion before creating a tracked resource.
- Unlinked ordinary messages wait briefly for an out-of-order correlated mention, then become ignored rather than creating a resource.
- Canonical principals, messages, revisions, and pending context are stored before access decisions.
- Provider permalink resolution is optional and occurs outside the persistence transaction. Controlled provider failures leave `original_url` null and do not hide the message.
- First invocation starts bounded `conversations.replies` hydration. Pages reconcile provider history into the same canonical message identities and update the high-watermark and event boundary.
- If routing becomes unavailable after hydration starts, hydration completes as
  `incomplete` with a routing-unavailable error rather than remaining `running`.
- Rate limits and temporary read failures defer the event with bounded retry timing.
  Invalid credentials and missing Slack scopes require reconnect but preserve routing.
  Lost resource access marks hydration incomplete and terminalizes the resource.

Activation waits until hydration is terminal and every correlated event through the persisted boundary is terminal. This prevents out-of-order or post-trigger/pre-activation message loss.

## Evidence and Redaction

Deterministic E2E uses signed raw callbacks and a fake HTTP/WebSocket provider through public APIs. Provider evidence records operation names, bounded metadata, acknowledgements, and state transitions only. Authorization headers, signing secrets, bot/app tokens, and Slack message text are excluded.

## Changelog

- **2026-07-23** (spec_version 4) — Removed route lifecycle state from ingress selection; active connection admission and active Agent lifecycle now determine routability.
- **2026-07-22** (spec_version 3) — Separated provider connection health from Agent routing, preserved routes across credential and permission failures, and required channel metadata scopes in generated Slack manifests.
- **2026-07-22** (spec_version 2) — Replaced per-connection selector callbacks with one fixed endpoint routed by Slack App/Team identity and authenticated by the selected connection's HMAC secret.
- **2026-07-22** (spec_version 1) — Promoted signed HTTP and fenced Socket Mode admission, asynchronous normalization/hydration, provider scope, retry behavior, and credential-free deterministic validation.
