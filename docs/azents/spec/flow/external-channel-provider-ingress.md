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
  - python/apps/azents/src/azents/services/external_channel/ingestion.py
  - python/apps/azents/src/azents/services/external_channel/ingestion_history.py
  - python/apps/azents/src/azents/services/external_channel/ingress_admission.py
  - python/apps/azents/src/azents/services/external_channel/conversation_provisioning.py
  - python/apps/azents/src/azents/services/external_channel/ingress_provisioning.py
  - python/apps/azents/src/azents/services/external_channel/ingress_queue.py
  - python/apps/azents/src/azents/services/external_channel/ingress_recovery.py
  - python/apps/azents/src/azents/services/external_channel/ingress_metrics.py
  - python/apps/azents/src/azents/services/external_channel/ingress_observability.py
  - python/apps/azents/src/azents/services/external_channel/ingestion_replay.py
  - python/apps/azents/src/azents/services/external_channel/mailbox_ingestion_store.py
  - python/apps/azents/src/azents/services/external_channel/mailbox_wake.py
  - python/apps/azents/src/azents/repos/external_channel/ingress_queue.py
  - python/apps/azents/src/azents/rdb/models/external_channel_ingress.py
  - python/apps/azents/src/azents/api/testenv/external_channel_ingress/**
  - python/apps/azents/src/azents/cli/external_channel_ingress.py
  - python/apps/azents/src/azents/services/external_channel/selector_state.py
  - python/apps/azents/src/azents/services/external_channel/transport_ingestion.py
  - python/apps/azents/src/azents/services/external_channel/connection_revocation.py
  - python/apps/azents/src/azents/services/external_channel/provider_control.py
  - python/apps/azents/src/azents/services/mailbox.py
  - python/apps/azents/src/azents/repos/agent_session/**
  - python/apps/azents/src/azents/services/root_agent_session_creation/**
  - python/apps/azents/src/azents/repos/agent_automatic_project/**
  - python/apps/azents/src/azents/services/external_channel/provider.py
  - python/apps/azents/src/azents/services/external_channel/slack_endpoint.py
  - python/apps/azents/src/cli/externalchannelgateway.py
  - testenv/azents/e2e/src/support/slack_provider_fake.py
  - testenv/azents/e2e/src/support/discord_provider_fake.py
  - testenv/azents/e2e/src/tests/required/public/test_external_channels.py
api_routes:
  - /external-channel/v1/slack/events
  - /external-channel/v1/discord/interactions/{selector}
last_verified_at: 2026-08-19
spec_version: 47
---

# External Channel Provider Ingress

## Scope

The Slack adapter accepts app-member public or private channel traffic plus signed
Slash Commands, message shortcuts, block actions, and modal submissions. Authenticated
Slack `block_suggestion` option requests return the explicit unsupported result and
perform no settings mutation. The
Discord adapter accepts target-Guild typed SDK message callbacks and signed command,
message-context, component, option, and modal interactions. Slack Connect, Discord
DMs/group DMs, reactions, and unrelated bot auto-triggers are outside the current
scope. A tracked conversation is an explicit parent-channel or thread Resource
resolved to one available Agent route whose Agent lifecycle is active.

Slack invocation classification accepts the provider-native `app_mention` event and
also a subtype-free human `message` whose bounded text explicitly references a
same-Team Bot User identity from the authenticated callback authorization or current
connection configuration. Other `message` callbacks remain context-only, including
connected-App output, unrelated mentions, and visible message subtypes.

Discord invocation classification accepts either a direct mention of the connected
Bot user or a mention of a Discord-managed role whose provider-owned Bot tag matches
that same validated connection Bot identity. Role names, ordinary role membership,
manually created roles, and other Bots' managed roles do not invoke the Agent. The
typed Gateway projection filters against the validated connection Bot identity before
retaining only the bounded matching role and owning-Bot identities; unresolved role
state fails closed without a provider REST lookup or durable role configuration.

Discord Gateway discovery, heartbeat, reconnect, Resume, and typed callbacks are owned
by the public high-level `discord.Client`. Each callback is immediately converted to a
bounded Azents projection before lease-fenced admission. Deterministic testenv
composition injects an SDK-facing factory and Gateway runner through credential-free
operation fixtures; it does not mutate SDK globals, emulate private SDK HTTP state, or
run a duplicate Discord Gateway protocol server.

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
6. Original message triggers enter DB-only durable admission. An explicit
   eligible top-level trigger first resolves the selected route and participation
   setting. If no setting exists, it creates or replaces one setup claim and setup
   control in the provider parent channel with no Binding, Session, canonical mailbox
   input, wake, or AgentRun.
   Configured traffic resolves one effective target conversation owner and inserts or
   reuses one content-free active ingress item even when its Binding and Session do not
   exist yet. A new
   eligible explicit mention in an existing Binding may additionally create one
   idempotent settings entry point; ordinary traffic, deployment, startup, and the
   drain worker do not create it.
   Existing-Binding admission reads Session availability without taking a Session
   row lock. The final canonical mailbox transaction conditionally transitions only
   an active, non-stopping Session to its wake state; failure rolls back the prepared
   mailbox input and leaves the ingress item recoverable.
7. The callback acknowledges after the ingress transaction commits. It does not wait
   for Local Job Runtime submission, provider exact/history I/O, mailbox admission,
   conversation-position advancement, Session wake, or provider-control delivery.
   Provider-resolution and wake failures are recovered from the durable active queue
   and canonical mailbox state rather than by withholding the transport response.

Payload App/Team identity is an index key, not authentication. Missing, unknown, or
ambiguous candidates fail closed, and ordinary events never pass admission without
successful HMAC verification.

Duplicate callbacks converge through the active-ingress deduplication key,
conversation position, and deterministic per-message mailbox identities.

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
boundary in the owning interaction before acknowledgement. A Multi App top-level
invocation with no valid channel default creates or replaces the channel setup claim
in `pending_agent`; its selector lists only routes the initiating principal may invoke.
Selection creates the provider-principal-authored default and moves that same claim to
`pending_location` without creating a Binding or Session. The provider trigger ID is
carried only in the in-memory handoff needed for the immediate modal mutation; it is
never persisted, logged, or replayed.

Supported signed Slash Commands, Message Commands, message-context shortcuts,
presence actions, components, Discord options, and modal submissions dispatch through
explicit setup/settings operation kinds. Slack option requests remain authenticated
but unsupported. Each supported callback revalidates the current setup source revision,
selected route, participation-setting or Binding generation, actor, and parent/thread scope.
Stale or unprovable scope returns a bounded current-state or unsupported result without
falling back to a parent mutation.

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

The SDK direct message callback remains the serial transport admission boundary. It passes bounded
text envelopes to Azents, where public `SocketModeRequest` and `SocketModeResponse`
types validate structure and construct the acknowledgement. Events API and interaction
envelopes enter the same DB-only durable admission service as HTTP. The exact envelope
acknowledgement is sent after the active ingress item commits and before provider
history, mailbox, or wake work. The SDK queue remains enabled without Azents message
listeners so it can process provider `disconnect` controls and perform endpoint
replacement.

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
message identity; the current lease/configuration/App-claim fence protects DB-only
admission without exposing Gateway transport state. Each delivered callback attempts
durable admission independently. A failure for one callback does not discard later
callbacks already delivered by the SDK; transport lifecycle failures remain owned by
the high-level client and fenced lease manager.

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

## Durable Batched Conversation Ingress

Normal Slack HTTP, Slack Socket Mode, and Discord Gateway message-create callbacks use
one provider-neutral admission and drain contract. The authenticated callback
contributes only a bounded typed trigger locator, conversation scope, and current
configuration or lease authority. Raw callback content is neither canonical input nor
durable queue content.

1. A short transaction revalidates the current connection, route, participation,
   access, Resource, and any existing Binding/Session filters. It creates or locks the
   physical source Resource and resolves the effective target Resource. Slack uses the
   parent channel for `location=channel` and the exact root/thread conversation for
   `location=threads`. Discord parent messages use the parent channel, while messages
   inside an existing Discord Thread use that Thread as an independent target.
   When Discord re-emits the exact starter message after Azents provisions a delivery
   Thread for a parent-channel root, exact retained source-channel, root-message, and
   delivery-channel labels normalize that replay back to the original parent-channel
   root scope while preserving the delivery Thread identity. Provider-native Thread
   starters remain independent Thread targets.
   An ordinary non-invocation stops before queue insertion when no connected Binding
   exists or its response mode is `mention_only`. Parent-channel participation and
   `all_messages` authority never admit ordinary traffic from an unbound Discord
   Thread. An eligible
   top-level invocation with no setting creates or replaces setup state and returns
   before queue insertion.
2. Configured traffic locks or creates one active conversation owner unique to the
   effective target Resource and inserts or reuses one content-free item. A ready owner
   freezes a connected Binding and active Session; a provisioning owner has neither.
   Items retain their physical source Resource and position separately from the target,
   plus provider/routing identity, trigger correlation, queue order, attempt state, and
   processing fences. Live Slack and Discord callbacks also retain only the bounded
   count of projected file entries, not their bytes or provider URLs. PostgreSQL is the
   correctness authority; Redis and in-memory conversation locks are not used for
   ordering, cursor correctness, or recovery.
3. After commit, the producer submits an owner-scoped execution key to the bounded
   Local Job Runtime. API and External Channel Gateway producers also scan due owners
   at startup and periodically, honoring owner preparation backoff and submitting rows
   whose lease is absent or expired. Callbacks within one active owner lifecycle
   coalesce, while empty-owner deletion and recreation starts a distinct lifecycle.
   Submission and scans are wake mechanisms rather than durable job authority.
4. A drain first conditionally claims the owner lease. If the owner is not ready, it
   prepares the provider conversation outside a database transaction. Discord
   per-thread mode reconciles or creates the actual delivery thread through the public
   SDK; Discord parent-channel mode and Slack use their existing provider conversation
   identity without an artificial mutation.
5. One short ready transaction re-locks the owner and current routing authority,
   retains the prepared Discord delivery thread on the target Resource when needed,
   reuses a compatible connected Binding/active Session or creates one root Session,
   Binding, Channel Work, and initial controls, then records the Binding/Session on the
   same owner without moving its items. A stopped Session, disconnected Binding, stale
   setting, or terminal provider result cannot become ready.
6. A ready owner's first claim contains exactly one due item; later claims contain at
   most ten due items in queue-key order. Resolution is sequential in that order
   outside a database transaction. A retry-waiting item does not block later due work.
7. Before provider history I/O, the handler suppresses an item already at or behind the durable
   conversation cursor. Otherwise the provider policy reads an exclusive-start,
   inclusive-trigger exact/history range, retaining the current bounded visible
   context and one leading omission marker. A same-batch tentative cursor prevents
   avoidable duplicate reads without reordering admitted callbacks. If the canonical
   trigger snapshot exposes fewer bounded files than the live callback observed, the
   read is a temporary history failure and the existing item retry/backoff policy
   reprocesses it.
8. The final transaction re-locks the owner, claimed items, connection
   authority, and affected conversation positions. It validates the initial cursor
   snapshot, correlates every returned provider message with every active admitted
   trigger identity, and assigns `prompt_role = context | invocation`. The exact
   trigger for any admitted item is `invocation`, including connected `all_messages`
   traffic whose provider-native explicit-invocation flag is false; retained messages
   without another active admitted correlation remain `context`. A stale cursor rolls
   back the complete prepared batch and retries coordination without consuming a
   provider attempt.
9. Every canonical provider message is admitted as one independent
   `external_channel_message` mailbox row. Rows from one processing batch share an
   order group with contiguous sequence values following queue order and per-item
   provider-history order.
10. In the same transaction, successful cursor advances, mailbox rows, retry-tail
   transitions, bounded-failure deletions, queue completion, drain-state update, and
   the existing Session runnable transition commit atomically. Retry retains the same
   ingress identity and original age while assigning a fresh tail key. Successful,
   suppressed, and bounded-failure items are deleted; no completed outcome or
   tombstone row is created.
11. A non-empty processing batch emits one post-commit routing-only
   `SessionWakeUp(session_id)`. Broker failure does not roll back mailbox input.
   Existing pending-mailbox and stuck-Session recovery consume the committed input
   without provider resend or a durable wake row.

Provisioning and item history each have at most five provider attempts and at most five
minutes of original owner/item age. Retryable preparation retains every item unchanged,
sets one bounded owner due time, releases the lease, and is not resubmitted before that
time. Attempt/age exhaustion, excessive delay, stale authority, malformed provider
data, stopped Session state, and terminal provider classifications emit one sanitized
warning and remove the applicable active owner/items or item. Raw provider errors and
message content are never logged. An exact-trigger-missing classification emits a
specific sanitized warning, deletes that item without retry or mailbox admission, and
continues processing the remaining batch. A later eligible provider redelivery may
create a new owner only after the terminal owner is gone.

An exact connected thread Binding wins route resolution. Otherwise Single uses its
sole route, Multi uses one valid channel default, and the active participation setting
selects parent-channel or addressed-thread behavior. Missing settings return only
explicit eligible top-level invocations to setup. Empty, removed, stale, or ambiguous
catalogs never fall back to an arbitrary Agent. Selected setup replay snapshots the
Agent's current automatic Project policy through the shared root Session creation
boundary. Before selected setup or allowed-access replay creates a Discord per-thread
Binding/Session, it uses the same provider conversation preparation service outside
the creation transaction. The final transaction revalidates the exact target, records
the prepared delivery thread, and only then creates Session state. Shared root
creation performs its preliminary Agent authority read without a row lock and uses
one final capability/version conditional update after Runtime FK-dependent context
persistence; stale authority rolls back the Binding, Session, and replay atomically.
Retry reconciles an
indeterminate provider create before repeating the idempotent transaction; an existing
Binding keeps its prior snapshot and bypasses provider preparation.

The shared response predicate admits explicit invocations in either mode and ordinary
messages on an existing connected `all_messages` Binding. Every Binding creation
remains mention-gated. A Discord Thread has participation state independent from its
parent channel, so a parent Binding or response-mode setting cannot admit an ordinary
message from an unbound Thread. After an explicit Thread invocation creates its exact
Binding, that Binding's response mode controls continuation only inside the Thread.
Ignored ordinary messages leave the
conversation position unchanged, so a later eligible mention can include them through
the existing bounded provider-history range. Already committed
mailbox input, wake, Channel Work, or AgentRun state is never cancelled or
reclassified by a later mode change. The explicit-invocation flag remains the
response-mode and settings-control signal; it does not demote an ordinary message that
already passed the connected `all_messages` gate. That admitted item's exact trigger
correlation produces `prompt_role=invocation`.

Restricted access persists the trigger source plus immutable conversation-position,
range-start, and trigger-position replay authority and returns one immediate
approval-control plan without waking a Session. For a setup-linked request, Allow commits the grant
and resumes `pending_location` setup without creating a Binding or entering access
replay. Legacy configured-thread Allow invokes the same DB-only admission service with
its durable replay boundary. Replay works whether the shared position is still before
the trigger or has advanced, and converges on active-ingress and per-message mailbox
identities.
Deny, block, revocation, malformed triggers, and non-invoking edit/delete callbacks
never release new Session input.

Slack message normalization prefers non-blank provider fallback text and otherwise
derives bounded readable content from supported Block Kit elements. Discord uses its
typed SDK projection. Bounded identity mappings, provider links, and metadata-only file
entries are derived by the history adapter. Slack provider operations use public
high-level `AsyncWebClient` methods with retries disabled; direct HTTP remains limited
to authenticated private-file streaming and presigned upload bodies.

Authenticated Slack App uninstall and token revocation bypass normal message
ingestion and directly apply fenced connection lifecycle handling. Token revocation
moves the current connection to `reconnect_required` without terminating bindings.
App uninstall terminally disconnects the connection, creates one leave-presence
control for each newly disconnected binding, captures its provider target before
credential purge, and attempts that target only after the terminal commit. Repeated
uninstall handling returns no additional cleanup plan. Invalid or stale admission
authority and malformed replay boundaries fail closed. Provider-history, cursor,
retry, and wake failures occur after durable admission and are recovered by the
Session drain lifecycle. Committed selector, approval,
joined-presence, leave-presence, and progress controls are attempted after their
commit without gating accepted input or terminal lifecycle state and without durable
provider work or recovery. Presence-control
Session links use only
`/w/{workspace}/agents/{agent}/sessions/{session}` and target the same durable Session
exposed by existing Agent Session list and detail APIs.

## Active Ingress Diagnostics

The read-only `external_channel_ingress status` operator CLI and guarded Testenv API
expose bounded active-state snapshots: queue counts, provider/connection identity,
Session and item age, attempt count, current batch and retry timing, lease
owner/generation/expiry, oldest queue age, and process-local aggregate metrics.
Metrics include claimed batch/item counts and size, processing duration, retry and
bounded-failure counts, cursor suppressions, mailbox rows committed, post-commit wake
attempts/failures, active Runtime tasks, and shutdown drain time.

The operator surface has no release, retry, delete, or other mutation command. The
guarded credential-free Testenv API may submit one exact Session through the real Job
Runtime and inject one exact one-shot wake failure. Neither surface exposes callback
bodies, message text, participant data, credentials, tokens, signatures, private URLs,
or raw provider errors.

## File Metadata Projection

Slack HTTP, Socket Mode, and provider-history projection use the same bounded Slack
`files[]` metadata. At most 20 entries are retained. Text fields are
bounded, malformed or truncated items fail closed, and no private URL or file body enters
the mailbox projection or Agent context.

Direct hosted uploads with an ID, supported mode, visible access, and no external or
Slack Connect classification receive a provider-addressed
`external-file:v1:<provider>:<binding>:<channel>:<message>:<file>` key. Slack leaves
channel and message empty; Discord includes both. External files, Slack Connect files, sparse
access-check records, unsupported modes, and missing IDs remain visible with stable
unsupported reasons but cannot be downloaded. Missing or malformed provider metadata
size remains visible as absent advisory data and does not make an otherwise supported
hosted attachment unavailable.

The first Agent turn, replay, filters, compaction continuity, structured visible values,
and token accounting render the same ordered metadata and direct keys. Rendering an
attachment never materializes its bytes. Explicit download later rechecks active
ownership, directional capability, `files.info` metadata, provider authorization,
and provider identity. The authenticated final URL `Content-Length` is the sole
declared transfer size; the GET response declaration and actual streamed bytes must
match it exactly.

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

- **2026-08-19** (spec_version 47) — Removed the preliminary Agent row lock
  from External Channel root Session creation and retained removal/lifecycle
  fencing through a final capability/version conditional update.
- **2026-08-18** (spec_version 46) — Removed the read-only Session row lock from
  existing-Binding trigger admission and made the final conditional mailbox wake
  transition the authoritative lifecycle fence.
- **2026-08-17** (spec_version 45) — Made exact-trigger-missing ingress explicitly
  warn, delete the item without retry or mailbox admission, and continue the batch.
- **2026-08-17** (spec_version 44) — Removed the broad ingress-drain diagnostic
  lifecycle contract introduced in version 43.
- **2026-08-16** (spec_version 43) — Added content-free execution, lease, batch,
  stage, deadline, cancellation, and duration correlation for ingress drain
  diagnostics.
- **2026-08-16** (spec_version 42) — Normalized the exact Discord starter replay from
  an Azents-provisioned delivery Thread back to its parent-channel root history scope
  while preserving provider-native Thread starter scope.
- **2026-08-14** (spec_version 41) — Made Discord Thread participation independent
  from its parent channel: unbound Thread traffic is mention-gated, while an existing
  Thread Binding retains its own `all_messages` continuation.
- **2026-08-14** (spec_version 40) — Stopped Discord Thread traffic from fanning
  into a `location=channel` parent conversation and allowed an unbound Thread to
  inherit configured `all_messages` authority for its independent Binding.
- **2026-08-13** (spec_version 39) — Persisted the bounded file count observed by live
  Slack and Discord callbacks and classified a shorter provider-history trigger
  snapshot as temporary so attachment propagation races use the existing ingress
  retry/backoff path.
- **2026-08-11** (spec_version 38) — Required every active admitted trigger identity,
  not only provider-native explicit mentions, to correlate its exact human provider
  message to `prompt_role=invocation`; connected `all_messages` triggers now remain
  invocation-role while retained history remains context.
- **2026-08-10** (spec_version 37) — Made the existing unbound-conversation rule
  explicit: every Binding creation is mention-gated, while `all_messages` applies only
  to ordinary continuation on a connected Binding.
- **2026-08-10** (spec_version 36) — Generalized callback admission to
  effective-conversation owners that can retain triggers before Binding/Session
  creation, prepare required Discord threads before the atomic ready transition,
  preserve source-thread fan-in, bound owner retry/cleanup, and reuse the same
  preparation boundary for setup/access replay.
- **2026-08-10** (spec_version 35) — Replaced synchronous normal-message ingestion
  with content-free PostgreSQL admission, first-one/later-ten Session drains,
  per-message mailbox rows and `prompt_role`, cursor-CAS batching, retry-tail recovery,
  one post-batch wake, and bounded read-only ingress diagnostics.
- **2026-08-04** (spec_version 33) — Made provider metadata size advisory for Slack
  and Discord attachments. Download eligibility now relies on identity and provider
  support, while the final authenticated URL `Content-Length` exclusively declares
  transfer size.
- **2026-08-03** (spec_version 32) — Added creation-only mailbox title eligibility
  consumed by the exact authorized human trigger during promotion without gating
  admission, wake, or execution.
- **2026-08-02** (spec_version 31) — Replaced committed provider-control intents and
  Worker delivery with process-local plans attempted once after the transport
  acknowledgement boundary, independently from canonical mailbox execution.
- **2026-08-02** (spec_version 30) — Accepted the connected Discord Bot's
  provider-managed role mention as an explicit invocation while rejecting arbitrary,
  manually created, and other-Bot roles.
- **2026-08-02** (spec_version 28) — Inserted latest-source channel setup before
  provider-history I/O, added selected setup replay and explicit settings interaction
  dispatch, preserved exact thread-Binding precedence, and fenced final admission by
  participation location, setting generation, and selected Agent.
- **2026-08-01** (spec_version 27) — Added the shared binding response-mode
  predicate at preparation and final admission, preserving ignored messages as later
  bounded context without provider-history I/O, mailbox input, wake, or position
  advancement.
- **2026-08-01** (spec_version 26) — Replaced the initial button-only Session link
  with a joined-presence control, added idempotent App-uninstall leave presence, and
  preserved independent post-commit delivery.
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
