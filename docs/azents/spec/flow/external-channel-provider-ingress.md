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
  - /external-channel/v1/slack/events/{selector}
last_verified_at: 2026-07-22
spec_version: 1
---

# External Channel Provider Ingress

## Scope

The Slack adapter accepts only app-member public or private channel traffic. Slack Connect, DMs, group DMs, shortcuts, reactions, slash commands, and unrelated bot auto-triggers are outside the current scope. A tracked conversation is one Slack thread rooted by an eligible App mention and owned by an active dedicated Agent route.

## HTTP Admission

1. The callback selector identifies a candidate HTTP connection without exposing its secret.
2. The adapter reads a bounded raw body and validates Slack timestamp freshness and HMAC signature against the encrypted signing secret.
3. URL verification returns the supplied challenge after the same authentication checks.
4. Event callbacks validate App/tenant identity and supported event shape, then persist the raw provider event idempotently.
5. Success is acknowledged only after durable admission. Admission does not decrypt provider content into domain rows, hydrate history, authorize a participant, create an AgentSession, wake an Agent, or call a provider mutation API.

Duplicate `(connection_id, provider_event_id)` callbacks reuse the admitted event and still receive a successful acknowledgement.

## Socket Mode Admission

A connection-selected Socket worker acquires a fenced lease before opening `apps.connections.open` with the app-level token. The WebSocket client admits Events API envelopes through the same durable admission service and sends the exact envelope acknowledgement only after admission returns. Failed admission remains unacknowledged.

Socket refresh/reconnect reasons are normalized. Invalid authentication and terminal provider disconnect reasons move the connection to `reconnect_required`; gap reasons are persisted for operators. Lease owner and expiry fence heartbeat, renew, release, gap, and active-state writes. Shutdown and cancellation close the socket and release ownership without exposing tokens.

Production permits only secure Slack endpoints. Test-only HTTP and insecure WebSocket overrides require explicit `AZ_TESTENV_SLACK_*` configuration.

## Asynchronous Processing

The worker claims admitted events in bounded batches with a claim owner and expiry. Processing is at-least-once and every canonical insert/update is idempotent.

- Revocation events terminalize the connection and route.
- Eligible invocation messages validate channel membership and Slack Connect/DM exclusion before creating a tracked resource.
- Unlinked ordinary messages wait briefly for an out-of-order correlated mention, then become ignored rather than creating a resource.
- Canonical principals, messages, revisions, and pending context are stored before access decisions.
- Provider permalink resolution is optional and occurs outside the persistence transaction. Controlled provider failures leave `original_url` null and do not hide the message.
- First invocation starts bounded `conversations.replies` hydration. Pages reconcile provider history into the same canonical message identities and update the high-watermark and event boundary.
- Rate limits and temporary read failures defer the event with bounded retry timing. Invalid credentials require reconnect. Lost resource access marks hydration incomplete and terminalizes the resource.

Activation waits until hydration is terminal and every correlated event through the persisted boundary is terminal. This prevents out-of-order or post-trigger/pre-activation message loss.

## Evidence and Redaction

Deterministic E2E uses signed raw callbacks and a fake HTTP/WebSocket provider through public APIs. Provider evidence records operation names, bounded metadata, acknowledgements, and state transitions only. Authorization headers, signing secrets, bot/app tokens, and Slack message text are excluded.

## Changelog

- **2026-07-22** (spec_version 1) — Promoted signed HTTP and fenced Socket Mode admission, asynchronous normalization/hydration, provider scope, retry behavior, and credential-free deterministic validation.
