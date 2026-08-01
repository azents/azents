---
title: "External Channel Provider Ingress"
created: 2026-07-22
tags: [backend, external-channel, slack, discord, ingress, security]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation]
code_paths:
  - python/apps/azents/src/azents/api/public/external_channel/v1/route.py
  - python/apps/azents/src/azents/services/external_channel/admission.py
  - python/apps/azents/src/azents/services/external_channel/http_admission.py
  - python/apps/azents/src/azents/services/external_channel/interaction.py
  - python/apps/azents/src/azents/services/external_channel/selector.py
  - python/apps/azents/src/azents/services/external_channel/shortcut_source.py
  - python/apps/azents/src/azents/services/external_channel/slack_http.py
  - python/apps/azents/src/azents/services/external_channel/slack_sdk_client.py
  - python/apps/azents/src/azents/services/external_channel/slack_socket.py
  - python/apps/azents/src/azents/services/external_channel/socket_manager.py
  - python/apps/azents/src/azents/services/external_channel/gateway_runtime.py
  - python/apps/azents/src/azents/services/external_channel/slack_blocks.py
  - python/apps/azents/src/azents/services/external_channel/slack_events.py
  - python/apps/azents/src/azents/services/external_channel/discord_http.py
  - python/apps/azents/src/azents/services/external_channel/discord_interaction.py
  - python/apps/azents/src/azents/services/external_channel/discord_gateway.py
  - python/apps/azents/src/azents/services/external_channel/discord_gateway_manager.py
  - python/apps/azents/src/azents/services/external_channel/discord_events.py
  - python/apps/azents/src/azents/services/external_channel/discord_history.py
  - python/apps/azents/src/azents/services/external_channel/discord_selector.py
  - python/apps/azents/src/azents/services/external_channel/access.py
  - python/apps/azents/src/azents/core/external_channel_file.py
  - python/apps/azents/src/azents/services/external_channel/conversation.py
  - python/apps/azents/src/azents/services/external_channel/conversation_lock.py
  - python/apps/azents/src/azents/services/external_channel/ingestion.py
  - python/apps/azents/src/azents/services/external_channel/ingestion_history.py
  - python/apps/azents/src/azents/services/external_channel/ingestion_replay.py
  - python/apps/azents/src/azents/services/external_channel/mailbox_ingestion_store.py
  - python/apps/azents/src/azents/services/external_channel/mailbox_wake.py
  - python/apps/azents/src/azents/services/external_channel/selector_state.py
  - python/apps/azents/src/azents/services/external_channel/transport_ingestion.py
  - python/apps/azents/src/azents/services/external_channel/connection_revocation.py
  - python/apps/azents/src/azents/services/external_channel/provider_control.py
  - python/apps/azents/src/azents/services/root_agent_session_creation/**
  - python/apps/azents/src/azents/repos/agent_automatic_project/**
  - python/apps/azents/src/azents/services/external_channel/provider.py
  - python/apps/azents/src/azents/services/external_channel/slack_endpoint.py
  - python/apps/azents/src/cli/externalchannelgateway.py
  - testenv/azents/e2e/src/support/slack_provider_fake.py
  - testenv/azents/e2e/src/support/discord_provider_fake.py
  - testenv/azents/e2e/src/tests/azents/public/test_external_channels.py
api_routes:
  - /external-channel/v1/slack/events
  - /external-channel/v1/discord/interactions/{selector}
last_verified_at: 2026-08-01
spec_version: 25
---

# External Channel Provider Ingress

## Scope

The Slack adapter accepts app-member public or private channel traffic plus the
supported message-shortcut and selector interaction callbacks. The Discord adapter
accepts target-Guild typed SDK message callbacks and signed interaction callbacks. Slack
Connect, Discord DMs/group DMs, reactions, slash commands, and unrelated bot
auto-triggers are outside the current scope. A tracked conversation is one provider
thread rooted by an eligible App mention or message shortcut and resolved to one
available Agent route whose Agent lifecycle is active.

Slack invocation classification accepts the provider-native `app_mention` event and
also a subtype-free human `message` whose bounded text explicitly references a
same-Team Bot User identity from the authenticated callback authorization or current
connection configuration. Other `message` callbacks remain context-only, including
connected-App output, unrelated mentions, and visible message subtypes.

## HTTP Admission

Slack sends HTTP callbacks to the single fixed endpoint
`POST /external-channel/v1/slack/events`.

1. The adapter reads a bounded raw body and parses only the minimum routing envelope.
2. A bounded `url_verification` request returns its challenge without connection
   lookup, durable admission, or Agent side effects.
3. An ordinary event uses untrusted `(api_app_id, team_id)` payload identity to select
   exactly one active or degraded HTTP connection.
4. The adapter uses the Slack SDK signature verifier to validate timestamp freshness
   and the raw-body HMAC signature against that candidate's encrypted Signing Secret.
5. The fully parsed event identity must match the selected connection before the
   authenticated request is projected into a typed, content-free trigger locator.
6. Original message triggers enter synchronous conversation ingestion. Provider
   history is read; then one transaction commits the real Session, binding, canonical
   mailbox input, conversation-position advance, running transition, and independent
   provider-control intents. The mailbox item is also the pending wake-recovery
   identity. Session-link or Tracker delivery never gates Agent execution.
7. Success is acknowledged only for a completed non-retryable outcome. A retryable
   coordination, history, position, or wake failure remains unacknowledged so the
   provider may retry.

Payload App/Team identity is an index key, not authentication. Missing, unknown, or
ambiguous candidates fail closed, and ordinary events never pass admission without
successful HMAC verification.

Duplicate callbacks converge through conversation position and deterministic mailbox
identity and still receive a successful acknowledgement after any pending wake is
recovered.

## Discord Interaction Admission

Discord sends interactions to
`POST /external-channel/v1/discord/interactions/{selector}`. The selector is an opaque
per-connection callback capability configured during activation; only its hash is
retained.

1. The adapter reads a bounded raw body.
2. It resolves exactly one current Discord configuration by selector hash.
3. It verifies the Discord Ed25519 signature against that connection's stored
   Application public key before parsing the body.
4. It verifies the submitted Application and Guild identities against the selected
   connection.
5. A verified endpoint PING returns its provider acknowledgement without durable
   interaction state.
6. A supported Message Command, component, autocomplete, or modal interaction creates
   or reuses one token-free durable interaction before its provider
   acknowledgement is returned. Message Commands materialize their selected source
   through the same canonical source-before-selection boundary; selector responses use
   signed compact component scope and return before any post-response control delivery.

Unknown selectors, malformed bodies, invalid signatures, mismatched Application/Guild
identity, and unsupported interaction types fail before durable interaction state. Discord
interaction tokens, raw bodies, and signatures remain request-local and are neither
persisted nor replayed.

## Interactive Admission and Selection

Signed Slack interaction callbacks use the same fixed endpoint and App/Team candidate
selection as Events API payloads. JSON events and form-encoded interactions are
bounded before parsing and authenticated against the selected connection's Signing
Secret.

Message shortcuts retain a content-free provider locator and conversation-position
boundary in the owning interaction before acknowledgement. A Multi App mention with no
valid channel default uses the same interaction-owned selector state and creates one
selector control. The provider trigger ID is carried only in the in-memory handoff
needed for the immediate modal mutation; it is never persisted, logged, or replayed.

Block actions open a paged/searchable modal from the current available route catalog.
Private metadata is signed and binds connection, resource, interaction, initiating
principal, original interaction, and page offset. Navigation and submission recheck
that scope, interaction expiry, route availability, Workspace boundary, and callback
actor before any selection. Duplicate callbacks reuse the durable interaction claim,
preserve any selected route, and one interaction can select at most once.

## Socket Mode Admission

The External Channel Gateway's Slack manager acquires a fenced lease before creating
one public aiohttp `SocketModeClient` with SDK automatic reconnect enabled. The SDK owns
`apps.connections.open`, secure endpoint selection and replacement, WebSocket
establishment, Ping/Pong, stale-session detection, frame receipt, queue dispatch, and
recoverable reconnect for that lease lifetime.

The SDK direct message callback remains the serial admission boundary. It passes bounded
text envelopes to Azents, where public `SocketModeRequest` and `SocketModeResponse`
types validate structure and construct the acknowledgement. Events API and interaction
envelopes enter the same synchronous durable services as HTTP, and the exact envelope
acknowledgement is sent only after a non-retryable outcome. Retryable ingestion remains
unacknowledged. The SDK queue remains enabled without Azents message listeners so it
can process provider `disconnect` controls and perform endpoint replacement.

An SDK connection establishment marks the current fenced lease active and clears its
gap. Endpoint replacement entry and transient endpoint acquisition failure record a
bounded degraded gap without completing the Azents runner. Invalid authentication
stops the current SDK lifecycle and moves only the connection to
`reconnect_required`; route catalog and historical state remain. Lease owner and
expiry fence heartbeat, renewal, admission, acknowledgement, release, gap, and active
writes. Shutdown, cancellation, or lease loss closes the SDK client before releasing
ownership.

Production permits only secure Slack endpoints. Test-only HTTP and insecure WebSocket overrides require explicit `AZ_TESTENV_SLACK_*` configuration.

## Discord Gateway Admission

The provider-neutral External Channel Gateway's Discord manager owns Gateway protocol
sessions beside the Slack Socket manager. It claims a configured Discord connection
with a lease owner, configuration generation, App-claim generation, and lease
generation. A stale claim cannot renew, admit, record a gap, or release newer
authority.

The manager uses only the public high-level `discord.py` client API. `Client.start`
owns Gateway discovery, Identify, heartbeat, reconnect, and in-process Resume. Azents
does not inspect Gateway frames, opcodes, session IDs, sequence numbers, Resume URLs,
raw payload dictionaries, or private SDK state, and it does not persist or inject an
SDK Resume checkpoint across processes.

Ingress consumes eligible target-Guild typed `Message` callbacks for normal
conversation ingestion. Message identity derives from Guild, channel, thread, and
message identity; the current lease/configuration/App-claim fence protects synchronous
admission without exposing Gateway transport state. Message and lifecycle callbacks
are serialized per connection, and a callback failure closes the high-level client so
it cannot be logged and ignored while the lease continues.

Typed `on_disconnect` records a fenced degraded gap. Typed `on_ready` and `on_resumed`
mark the same current lease active and clear its gap. A stale callback fails the client
and cannot mutate a newer lease.

Credential failures and Gateway outcomes that cannot reconnect terminalize the current
fenced lease in one transaction: they record the reason, release that lease, and move
the connection to `reconnect_required`. The scheduler excludes that state until a
validated configuration edit reactivates the connection. Recoverable Gateway and
network failures retain the normal gap-and-retry behavior.

Production Gateway transport is selected and validated by `discord.py`; Azents does
not change SDK endpoint state in production. Deterministic provider tests may apply one
explicit test-only endpoint context and must restore the SDK globals when the client
closes.

## Synchronous Conversation Ingestion

Normal Slack HTTP, Slack Socket Mode, and Discord Gateway message-create callbacks use
one provider-neutral synchronous service under a shared absolute transport deadline.
The authenticated callback contributes only a typed trigger locator, conversation
scope, and current configuration or lease authority. Raw callback content is neither
the canonical message source nor a durable queue item.

1. The service acquires the configured ephemeral lock for the parent-channel or thread
   scope. In-memory locks coordinate one process. Redis locks coordinate replicas and
   use owner-token fencing; Redis unavailability is a retryable failure and never
   switches implicitly to memory.
2. A short preparation transaction revalidates ingress authority, creates or reads the
   PostgreSQL conversation position, resolves existing binding/selector/access state, and
   returns the exclusive provider-history start position. It performs no provider I/O.
3. The provider adapter reads an exclusive-start, inclusive-trigger history range
   outside any database transaction. It retains the newest 20 eligible visible
   messages and records one leading omission reminder when earlier eligible context
   was omitted. The connected Azents App/Bot is excluded; raw REST pages, callbacks,
   tokens, private URLs, and attachment bodies are not retained.
   Slack display-name and permalink enrichment is optional and starts only while a
   fixed reserve remains for durable acceptance and wake dispatch.
4. A short admission transaction locks and revalidates the same authority,
   conversation position, active resource, route/binding/selector, and access
   boundary. It creates or reuses the connected binding, real root Session, initial
   Channel Work, deterministic canonical mailbox input, and deterministic Session-link
   and progress delivery intents. The same transaction marks the Session running,
   initializes thread position, and compare-and-set advances the conversation position.
   PostgreSQL conversation position is the sole duplicate-prevention and ordering
   authority; a mismatch restarts provider-history preparation.
5. After commit, the service claims the pending mailbox item and sends routing-only
   `SessionWakeUp(session_id)`. A crash or broker failure leaves that item recoverable,
   so duplicate transport delivery can complete the same logical wake without creating
   another Session input.
6. The Agent Worker attempts committed Session-link and progress controls through the
   shared one-attempt delivery fence. Delivered, failed, unknown, not-attempted, and
   cancelled outcomes remain provider-delivery evidence only; none gates mailbox
   promotion, Session wake, or AgentRun creation.

An existing connected binding wins route resolution. Otherwise Single uses its sole
route, Multi uses one valid channel default, and unresolved Multi traffic creates an
interaction-owned typed selection boundary. Empty, removed, stale, or ambiguous catalogs never fall
back to an arbitrary Agent. An already-granted first invocation snapshots the Agent's
current automatic Project policy through the shared root Session creation boundary;
an existing binding keeps its prior snapshot.

Restricted access persists the trigger source plus immutable conversation-position,
range-start, and trigger-position replay authority and commits an approval-control
intent without waking a Session. Allow invokes the same synchronous ingestion service
with that durable replay boundary. Replay works whether the shared position is still
before the trigger or has advanced, and converges on one mailbox identity.
Deny, block, revocation, malformed triggers, and non-invoking edit/delete callbacks
never release new Session input.

Slack message normalization prefers non-blank provider fallback text and otherwise
derives bounded readable content from supported Block Kit elements. Discord uses its
typed SDK projection. Bounded identity mappings, provider links, and metadata-only file
entries are derived by the history adapter. Slack provider operations use public
high-level `AsyncWebClient` methods with retries disabled; direct HTTP remains limited
to authenticated private-file streaming and presigned upload bodies.

Authenticated Slack App uninstall and token revocation bypass normal message
ingestion and directly apply fenced connection lifecycle handling. Provider-history,
coordination, position, or wake failures return a retryable transport outcome. Invalid
or stale authority and malformed replay boundaries fail closed. Committed selector,
approval, Session-link, and initial-progress controls are attempted after their commit
without gating accepted input. Provider Session links use only
`/w/{workspace}/agents/{agent}/sessions/{session}` and target the same durable Session
exposed by existing Agent Session list and detail APIs.

## File Metadata Projection

Slack HTTP, Socket Mode, and provider-history projection use the same bounded Slack
`files[]` metadata. At most 20 entries are retained. Text fields are
bounded, malformed or truncated items fail closed, and no private URL or file body enters
the mailbox projection or Agent context.

Direct hosted uploads with an ID, non-negative declared size, supported mode, visible
access, and no external or Slack Connect classification receive a provider-addressed
`external-file:v1:<provider>:<binding>:<channel>:<message>:<file>` key. Slack leaves
channel and message empty; Discord includes both. External files, Slack Connect files, sparse
access-check records, unsupported modes, missing IDs, and invalid sizes remain visible
with stable unsupported reasons but cannot be downloaded.

The first Agent turn, replay, filters, compaction continuity, structured visible values,
and token accounting render the same ordered metadata and direct keys. Rendering an
attachment never materializes its bytes. Explicit download later rechecks active
ownership, directional capability, `files.info` metadata, provider authorization,
declared size, and actual streamed bytes.

## Evidence and Redaction

Deterministic E2E uses signed raw callbacks and fake HTTP/WebSocket providers through
public APIs. Provider evidence records operation names, bounded metadata,
acknowledgements, Gateway state transitions, file counts, aggregate bytes, and outcomes
only. Authorization headers, signing secrets, bot/app tokens, callback URLs, raw
payloads, message text, attachment names, attachment bytes, and transient URLs are
excluded.

Slack SDK clients use dedicated non-propagating loggers so SDK diagnostics cannot
serialize provider request parameters, response bodies, or Socket endpoint details
into application logs.

The first successful creation of a real External Channel root AgentSession emits one
structured information log with only the provider and canonical provider event type.
Session reuse and idempotent retries emit no creation log. Provider tenant, channel,
participant, message, payload, and Session identifiers are excluded.

The External Channel Gateway supervises Slack Socket and Discord Gateway manager loops
as required process dependencies. Unexpected top-level return, cancellation, or failure
terminates the gateway instead of leaving readiness alive without one transport class.
Customer-specific terminal configuration remains durable connection-local health and
does not by itself make the shared gateway unready. General Agent Workers own Session
execution and do not own persistent provider connections.

## Changelog

- **2026-08-01** (spec_version 25) — Made PostgreSQL conversation position the sole
  duplicate-prevention authority and decoupled provider-control outcomes from
  canonical mailbox acceptance, Session wake, and AgentRun creation.
- **2026-07-31** (spec_version 24) — Recognized authenticated same-Team Slack Bot
  User mentions delivered as subtype-free human `message` callbacks while preserving
  fail-closed context handling for unrelated or App-authored messages.
- **2026-07-31** (spec_version 23) — Corrected Session navigation to the canonical
  `/w` route.
- **2026-07-31** (spec_version 22) — Reserved Slack optional-enrichment time for
  durable admission and made `disconnected_at` the binding relationship authority.
- **2026-07-31** (spec_version 21) — Moved Slack Socket Mode and Discord Gateway
  managers into one provider-neutral External Channel Gateway runtime, removed Socket
  supervision from Agent Workers, and preserved direct shared-ingestion calls.
- **2026-07-31** (spec_version 20) — Replaced conversation admissions,
  provider-message/revision storage, invocation batches, and wake dispatch with
  interaction/access replay boundaries and one canonical mailbox item; file keys now
  carry direct provider coordinates.
- **2026-07-31** (spec_version 19) — Delegated Slack Socket endpoint acquisition,
  queue control, stale detection, and recoverable reconnect to the SDK; added fenced
  Slack and Discord typed lifecycle health; moved Slack HTTP verification to the SDK
  verifier; and made the Slack manager part of Worker foreground supervision.
- **2026-07-30** (spec_version 18) — Replaced durable event admission,
  background processing, hydration, pending context, and waiting activation with
  synchronous typed message ingestion, provider-history authority, PostgreSQL
  conversation positions, atomic mailbox/wake admission, immutable replay, and direct
  lifecycle control handling.
- **2026-07-29** (spec_version 17) — Replaced the custom Slack WebSocket transport
  with the public aiohttp SDK Socket Mode client while preserving Azents-owned lease,
  durable admission-before-acknowledgement, reconnect decisions, and sanitized
  deterministic evidence.
- **2026-07-28** (spec_version 16) — Moved Slack Web API operations and Socket endpoint
  minting to public high-level SDK methods with retries disabled, retained
  Azents-owned WebSocket lifecycle with SDK typed envelopes and acknowledgements, and
  supervised admitted-event processor iterations after transient failures.
- **2026-07-28** (spec_version 15) — Restricted Discord Gateway ingress to public
  high-level `discord.py` APIs and complete typed message projections, and removed
  raw frame parsing, private SDK access, persisted Resume state, and custom endpoint
  overrides.
- **2026-07-28** (spec_version 14) — Replaced the custom Discord Gateway protocol
  loop with `discord.py`, added cache-independent Resume identity recovery and bounded
  retry backoff, and documented Discord identity/link projection budgets.
- **2026-07-28** (spec_version 13) — Added bounded Discord root/thread history
  hydration, reconciliation-fenced selector/approval activation, and signed
  Message-Command selector source materialization.
- **2026-07-27** (spec_version 12) — Terminalized fenced Discord Gateway credential
  and non-reconnectable outcomes so they cannot cause repeated scheduler claims.
- **2026-07-26** (spec_version 11) — Completed Discord mention routing through
  provider-neutral authorization, immediate binding activation, invocation release,
  Channel Work, and post-commit wake-up without provider-principal-to-User mapping.
- **2026-07-26** (spec_version 10) — Added selector-scoped Ed25519 Discord
  interaction admission and the dedicated lease-fenced Gateway Worker with
  admission-coupled checkpoints, secure production transport, and sanitized
  deterministic fake evidence.
- **2026-07-26** (spec_version 9) — Added signed shortcut and selector interaction
  admission, transient trigger handling, durable selection scope, and deterministic
  binding/default/Single route resolution.
- **2026-07-24** (spec_version 8) — Added already-granted initial binding root
  creation with Agent automatic Project snapshotting and existing-binding reuse.
- **2026-07-23** (spec_version 7) — Added bounded Slack file projection shared by HTTP,
  Socket, and hydration, stable unsupported reasons, opaque locators, and metadata-only
  Agent rendering.
- **2026-07-23** (spec_version 6) — Added bounded Block Kit and rich-text fallback normalization shared by HTTP callbacks, Socket Mode, hydration, and revision identity.
- **2026-07-23** (spec_version 5) — Excluded connected-App authored messages from ingress and hydration, and added best-effort bounded Slack identity-reference enrichment.
- **2026-07-23** (spec_version 4) — Removed route lifecycle state from ingress selection; active connection admission and active Agent lifecycle now determine routability.
- **2026-07-22** (spec_version 3) — Separated provider connection health from Agent routing, preserved routes across credential and permission failures, and required channel metadata scopes in generated Slack manifests.
- **2026-07-22** (spec_version 2) — Replaced per-connection selector callbacks with one fixed endpoint routed by Slack App/Team identity and authenticated by the selected connection's HMAC secret.
- **2026-07-22** (spec_version 1) — Promoted signed HTTP and fenced Socket Mode admission, asynchronous normalization/hydration, provider scope, retry behavior, and credential-free deterministic validation.
