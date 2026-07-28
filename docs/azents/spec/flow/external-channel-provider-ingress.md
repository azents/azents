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
  - python/apps/azents/src/azents/services/external_channel/slack_socket.py
  - python/apps/azents/src/azents/services/external_channel/socket_manager.py
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
  - python/apps/azents/src/azents/services/external_channel/event_processor.py
  - python/apps/azents/src/azents/services/root_agent_session_creation/**
  - python/apps/azents/src/azents/repos/agent_automatic_project/**
  - python/apps/azents/src/azents/services/external_channel/provider.py
  - python/apps/azents/src/azents/services/external_channel/slack_endpoint.py
  - python/apps/azents/src/azents/worker/worker.py
  - testenv/azents/e2e/src/support/slack_provider_fake.py
  - testenv/azents/e2e/src/support/discord_provider_fake.py
  - testenv/azents/e2e/src/tests/azents/public/test_external_channels.py
api_routes:
  - /external-channel/v1/slack/events
  - /external-channel/v1/discord/interactions/{selector}
last_verified_at: 2026-07-28
spec_version: 15
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
   admission.
6. A supported Message Command, component, autocomplete, or modal interaction creates
   or reuses one token-free durable interaction admission before its provider
   acknowledgement is returned. Message Commands materialize their selected source
   through the same canonical source-before-selection boundary; selector responses use
   signed compact component scope and return before any post-response control delivery.

Unknown selectors, malformed bodies, invalid signatures, mismatched Application/Guild
identity, and unsupported interaction types fail before durable admission. Discord
interaction tokens, raw bodies, and signatures remain request-local and are neither
persisted nor replayed.

## Interactive Admission and Selection

Signed Slack interaction callbacks use the same fixed endpoint and App/Team candidate
selection as Events API payloads. JSON events and form-encoded interactions are
bounded before parsing and authenticated against the selected connection's Signing
Secret.

Message shortcuts retain the selected source message and metadata-only files in a
durable conversation admission before acknowledgement. A Multi App mention with no
valid channel default also creates one pending admission and a selector control. The
provider trigger ID is carried only in the in-memory handoff needed for the immediate
modal mutation; it is never persisted, logged, or replayed.

Block actions open a paged/searchable modal from the current available route catalog.
Private metadata is signed and binds connection, resource, admission, initiating
principal, original interaction, and page offset. Navigation and submission recheck
that scope, admission expiry, route availability, Workspace boundary, and callback
actor before any selection. Duplicate callbacks reuse the durable interaction claim,
and one admission can select at most once.

## Socket Mode Admission

A connection-selected Socket worker acquires a fenced lease before opening `apps.connections.open` with the app-level token. The WebSocket client admits Events API envelopes through the same durable admission service and sends the exact envelope acknowledgement only after admission returns. Failed admission remains unacknowledged.

Socket refresh/reconnect reasons are normalized. Invalid authentication moves the
connection to `reconnect_required` without changing its route catalog. Socket-only gap
reasons are persisted for operators. Lease owner and expiry fence heartbeat, renew,
release, gap, and active-state writes. Shutdown and cancellation close the socket and
release ownership without exposing tokens.

Production permits only secure Slack endpoints. Test-only HTTP and insecure WebSocket overrides require explicit `AZ_TESTENV_SLACK_*` configuration.

## Discord Gateway Admission

The dedicated Discord Gateway Worker, rather than an Agent Worker, owns Gateway
protocol sessions. It claims a configured Discord connection with a lease owner,
configuration generation, App-claim generation, and lease generation. A stale claim
cannot renew, admit, record a gap, or release newer authority.

The Worker uses only the public high-level `discord.py` client API. `Client.start`
owns Gateway discovery, Identify, heartbeat, reconnect, and in-process Resume. Azents
does not inspect Gateway frames, opcodes, session IDs, sequence numbers, Resume URLs,
raw payload dictionaries, or private SDK state, and it does not persist or inject an
SDK Resume checkpoint across processes.

Ingress consumes the SDK's typed `Message`, `RawMessageUpdateEvent`, and
`RawMessageDeleteEvent` callbacks. Update admission reads the public typed `message`
projection rather than the event's raw data dictionary. Delete admission uses only the
typed message, channel, and Guild identifiers. Cache misses resolve channel or thread
identity through public `Client.get_channel` and `Client.fetch_channel` methods.
Callbacks are serialized per connection, and a callback failure closes the high-level
client so it cannot be logged and ignored while the lease continues.

The Worker accepts only eligible target-Guild message callbacks. Canonical event
identity derives from message lifecycle, Guild, channel, and message identity; update
identity additionally includes a bounded typed-projection fingerprint. Provider event
idempotency and the current lease/configuration/App-claim fence protect durable
admission without exposing Gateway transport state.

Credential failures and Gateway outcomes that cannot reconnect terminalize the current
fenced lease in one transaction: they record the reason, release that lease, and move
the connection to `reconnect_required`. The scheduler excludes that state until a
validated configuration edit reactivates the connection. Recoverable Gateway and
network failures retain the normal gap-and-retry behavior.

Production Gateway transport is selected and validated by `discord.py`; Azents does
not provide a custom Gateway endpoint override.

## Asynchronous Processing

The worker claims admitted events in bounded batches with a claim owner and expiry. Processing is at-least-once and every canonical insert/update is idempotent.

- Provider health failures and token revocation update connection health without
  changing route catalog state, bindings, or work.
- Every event-persistence and hydration-page transaction locks its `active` or
  `degraded` connection before route, resource, admission, and binding state. This
  common order serializes disconnect, route/default mutation, selection, and binding
  activation rather than allowing them to commit across one another.
- App uninstall terminalizes provider resources and credentials while preserving the
  route catalog for later reconfiguration.
- Eligible invocation messages validate channel membership and Slack Connect/DM exclusion before creating a tracked resource.
- An existing active binding always wins. Otherwise Single uses its sole route,
  Multi uses one valid channel default, and unresolved Multi traffic waits for
  explicit selection. Empty, removed, stale, or ambiguous catalogs never fall back
  to an arbitrary Agent.
- Unlinked ordinary messages wait briefly for an out-of-order correlated mention, then become ignored rather than creating a resource.
- Messages authored by the configured Slack App or bot are ignored during ordinary event processing and history hydration, preventing provider output from re-entering Agent context.
- Canonical principals, messages, revisions, and pending context are stored before access decisions.
- An eligible Discord mention uses the same durable route, admission, pending-context,
  block, grant, binding, invocation-batch, and mailbox boundaries as Slack. A Discord
  principal remains provider provenance and access-policy subject matter only; it is
  never inferred to be an Azents User.
- A granted Discord mention creates or reuses a `waiting_hydration` binding. It does
  not release retained context, create initial Session/progress delivery, or wake the
  Session until bounded Discord history reconciliation reaches its persisted event
  boundary. Selector and approval-created Discord bindings start the same hydration
  path during waiting-binding reconciliation.
- An ungranted Discord mention creates the durable access request and its
  provider-visible approval control without waking a Session. Allow releases the
  retained source message through the same invocation batch and mailbox boundary;
  block, revocation, or denial never release new input.
- When an eligible principal already has an Agent-scoped grant and the resource has
  no active binding, initial binding creation uses the shared root Session boundary
  to snapshot the Agent's current automatic Project policy into a new root
  `SessionAgentContext`. An existing binding is returned unchanged and retains its
  prior snapshot.
- Slack message normalization prefers non-blank provider fallback text. When it is absent, HTTP and Socket ingestion derive the same bounded readable body from supported section, header, context, and rich-text elements. User and channel elements retain reference syntax, unsupported elements contribute no text, and edit revision identity uses the resulting normalized body.
- Ingestion enriches revisions with bounded sender, mentioned-user, current-channel,
  thread, and parent-channel reference mappings when provider identity is available.
  The mapping's model-visible size participates in pending-context trimming. Missing
  optional display identity leaves canonical provider IDs and messages intact.
- Slack permalink resolution is optional and occurs outside the persistence
  transaction. Controlled Slack failures leave `original_url` null and do not hide the
  message. Discord derives its canonical message link only from validated Guild,
  channel, and message snowflakes.
- First invocation starts provider-dispatched bounded hydration. Slack reads
  `conversations.replies`; Discord reads only the canonical root source when no thread
  exists and pages an existing thread backward by message cursor. Both normalize pages
  into the same canonical message/revision identities and update the high-watermark and
  event boundary without persisting raw REST pages, tokens, or attachment URLs.
- If routing becomes unavailable after hydration starts, hydration completes as
  `incomplete` with a routing-unavailable error rather than remaining `running`.
- Rate limits and temporary read failures defer the event with bounded retry timing.
  Invalid credentials and missing Slack scopes require reconnect but preserve routing.
  Lost resource access marks hydration incomplete and terminalizes the resource.

Slack and Discord activation wait until hydration is terminal and every correlated
event through the persisted boundary is terminal. This prevents out-of-order or
post-trigger/pre-activation message loss. After that fence, retained context, the
active binding, invocation batch, mailbox item, Session navigation, and initial work
projection commit before the post-commit wake-up.

## File Metadata Projection

HTTP callbacks, Socket Mode envelopes, and `conversations.replies` hydration project the
same bounded Slack `files[]` metadata. At most 20 entries are retained. Text fields are
bounded, malformed or truncated items fail closed, and no private URL or file body enters
the canonical revision or Agent context.

Direct hosted uploads with an ID, non-negative declared size, supported mode, visible
access, and no external or Slack Connect classification receive a provider-neutral,
binding-scoped `external-file:v1` locator. External files, Slack Connect files, sparse
access-check records, unsupported modes, missing IDs, and invalid sizes remain visible
with stable unsupported reasons but cannot be downloaded.

The first Agent turn, replay, filters, compaction continuity, structured visible values,
and token accounting render the same ordered metadata and opaque locators. Rendering an
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

## Changelog

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
