---
title: "Discord Agent App Routing"
created: 2026-07-26
tags: [discord, external-channel, architecture, security, infra]
document_role: primary
document_type: adr
snapshot_id: discord-260726
---

# Discord Agent App Routing ADR

- Snapshot: `discord-260726`
- Document reference: `discord-260726/ADR`
- Requirements: [discord-260726/REQ](../requirements/discord-260726-agent-app-routing.md)

## Context

The confirmed Requirements make Discord observably equivalent to the current Slack
External Channel product while allowing provider-native mechanics. The existing
External Channel persistence graph, authorization model, Session binding, Channel
Work, lifecycle, and generation fences are substantially provider-neutral. The current
runtime adapter, credentials, ingress, interaction, file transfer, delivery,
presentation, management API, generated contract, and Web surfaces remain strongly
Slack-specific.

Discord creates architectural constraints that do not exist in Slack's signed HTTP and
Socket Mode model:

- ordinary server message events require persistent Gateway WebSocket connections;
- each customer-owned Discord App has its own bot token and Gateway session;
- interactions can arrive through either Gateway events or an outgoing HTTP webhook,
  but one App cannot use both interaction-delivery methods simultaneously;
- interaction tokens require an initial response within the provider deadline and are
  transient callback capabilities rather than durable execution authority;
- unmentioned follow-up message content depends on the privileged `MESSAGE_CONTENT`
  intent;
- message context commands can provide the selected source message required by the
  parity contract; and
- Discord can create a thread from an existing message, but the source message can own
  only one such thread and channel types have different thread behavior.

Historical nointern Discord designs are evidence only. They used a platform-owned bot
and source-specific Session tables, which conflict with the confirmed customer-owned
Single/Multi App model and the current External Channel canonical domain. Their useful
operational lessons are limited to keeping Gateway protocol handling lightweight,
separating it from business transactions, and expecting duplicate/replayed events.

## Confirmed Constraints

- `discord-260726/REQ` is the product source of truth and is not reopened by this ADR.
- Customer-owned Single and Multi Discord Apps retain separate credentials and provider
  identities; a shared platform bot cannot replace them.
- PostgreSQL remains canonical. Gateway processes, HTTP callbacks, brokers, and
  interaction tokens only route or wake durable work.
- Discord principals and callback actors remain provenance and authorization inputs;
  they never become the Azents execution User.
- Existing External Channel lock order, owner-generation fencing, immutable binding,
  approval, lifecycle, file authority, and commit-before-provider-call guarantees stay
  intact.
- Provider-specific payloads and capabilities are translated at adapter boundaries and
  do not redefine canonical Agent, Session, binding, work, or authorization state.

## Current System Evidence

- `ExternalChannelProvider` currently contains only `slack`.
- Connection credentials are currently a Slack-only payload union.
- Connection/route/resource/admission/binding/access/work/lifecycle repositories are the
  primary reusable domain boundary.
- Slack-specific code currently owns callback admission, Socket Mode leases, selector
  modal mutation, message normalization, history hydration, file transfer, delivery,
  progress lowering, validation, manifest guidance, and management handoff.
- Public API routes, generated clients, Web routes, translations, and deterministic E2E
  fixtures currently name Slack explicitly.

## External Platform Evidence

- [Discord Gateway](https://docs.discord.com/developers/events/gateway)
- [Receiving and Responding to Interactions](https://docs.discord.com/developers/interactions/receiving-and-responding)
- [Application Commands](https://docs.discord.com/developers/interactions/application-commands)
- [Application Resource](https://docs.discord.com/developers/resources/application)
- [Component Reference](https://docs.discord.com/developers/components/reference)
- [Channels Resource](https://docs.discord.com/developers/resources/channel)
- [Message Resource](https://docs.discord.com/developers/resources/message)
- [API Reference: Uploading Files](https://docs.discord.com/developers/reference#uploading-files)

## Research Synthesis

### Historical nointern evidence

The legacy implementation was inspected at its pre-removal revisions rather than
treated as an architectural template.

- The original BYOA model stored `mode`, one `agent_id`, and one encrypted bot token
  directly on a Discord installation. It was removed by `7fc0dde64` on 2026-03-11
  and cannot represent the confirmed Single/Multi App catalog or current External
  Channel ownership graph.
- The first Gateway ran inside the main nointern process and owned provider protocol,
  Session resolution, history, broker delivery, and outbound rendering. Operational
  fixes repeatedly separated channel and thread identity, pre-created threads, tracked
  provider message identities, refreshed typing state, split long messages, hardened
  uploads, and added rate-limit and 5xx retry behavior.
- The Gateway HA work beginning at `9be4fd347` extracted a lightweight `discord.py`
  process that forwarded signed HTTP callbacks to the API. This usefully separated
  persistent provider protocol from business transactions and deployment churn.
- That HA design assumed one platform-owned bot token and intentionally ran duplicate
  active Gateway sessions with Redis deduplication. Applying it once per
  customer-owned App would double every persistent connection, spend each App's
  independent session-start budget, and still require a new credential distribution
  mechanism.
- The legacy callback acknowledged neither durable PostgreSQL admission nor
  connection ownership generation. Its bounded retries could still lose an event after
  the final attempt. Current Azents must instead make durable admission and lease
  fencing part of the Gateway ownership contract.

### Current Discord contract

- Ordinary guild message events still require a Gateway session. Application Event
  Webhooks do not replace `MESSAGE_CREATE` delivery for this product flow.
- Every customer-owned App has an independent bot token, Gateway URL, session-start
  limit, concurrency allowance, privileged-intent configuration, and resumable Gateway
  session. A process restart must therefore be staggered per App rather than treated as
  one platform-bot reconnect.
- `MESSAGE_CONTENT` is required for the unmentioned follow-up content and attachments
  required by `discord-260726/REQ-10` and `discord-260726/REQ-15`. Without the enabled
  privileged intent, affected Gateway message fields are empty. A disallowed intent can
  also terminate the Gateway session, so setup validation and reconnect health must
  surface it explicitly.
- A message application command provides the selected source message in resolved
  interaction data. This satisfies the source-retention entry point required by
  `discord-260726/REQ-7` without a slash-command substitute.
- Interactions may be delivered through either Gateway `INTERACTION_CREATE` events or
  one configured outgoing HTTP endpoint, not both. The application endpoint URL can be
  updated through the Discord application API after Discord validates its signature
  handshake.
- Every interaction needs an initial response within three seconds. Its token remains
  usable for follow-up operations for 15 minutes, but it is a transient provider
  capability and is not suitable as durable execution authority.
- A Discord string select carries at most 25 options. The complete Multi App catalog
  therefore requires a durable page/search projection and scoped navigation rather
  than one static component payload.
- Starting a thread from an existing message creates a public or announcement thread
  whose ID equals the source message ID. A source message can have only one thread.
  Forum and media channels use a different creation contract and remain outside the
  confirmed first-release scope.
- Ordinary message content is limited to 2,000 characters. A Create Message request
  is limited to 25 MiB, and each uploaded file is also constrained by Discord's
  calculated maximum attachment size, whose default is 10 MiB and may be higher for
  the relevant interaction or server context. Discord lowering must preserve the
  configured External Channel policy through ordered multi-message delivery when
  necessary, while preflighting known provider limits and classifying provider
  rejection explicitly.

### Current Azents reuse boundary

- Connection, route, channel default, conversation admission, interaction, resource,
  event, principal, message revision, binding, access, Channel Work, action, and
  delivery records are reusable canonical state.
- The current connection lease fields and `SlackSocketManagerService` prove the
  repository can fence one persistent provider owner per connection, but the lease
  naming and implementation are Slack-specific.
- The existing interaction and shortcut services already implement durable source
  retention, immutable route selection, approval continuity, and transient trigger
  handling. Discord needs a provider presentation and callback adapter around those
  boundaries rather than a second routing domain.
- Credential unions, validation, ingress normalization, history hydration, selector
  rendering, delivery REST calls, progress presentation, file transfer, management
  routes, Web surfaces, generated clients, and deterministic fixtures require explicit
  Discord implementations or provider-neutral extraction.

## Open Decision Backlog

1. **Accepted as `discord-260726/ADR-D1`** — Gateway connection ownership, lease,
   and high-availability boundary for many customer-owned bot tokens.
2. **Accepted as `discord-260726/ADR-D2`** — Interaction ingress through Discord's
   outgoing HTTP endpoint rather than Gateway `INTERACTION_CREATE` events.
3. **Accepted as `discord-260726/ADR-D3`** — Canonical Discord conversation resource
   identity and when a provider thread is created or reused.
4. **Accepted as `discord-260726/ADR-D4`** — `MESSAGE_CONTENT` intent requirements,
   setup validation, and rollout gating.
5. **Accepted as `discord-260726/ADR-D5`** — Discord control visibility and
   interaction UI for selection, approval, Session navigation, and channel management.
6. **Accepted as `discord-260726/ADR-D6`** — Discord delivery presentation for Channel
   Work, Agent identity, long messages, and files.
7. **Accepted as `discord-260726/ADR-D7`** — Provider credential schema, installation
   validation, capability projection, and permission repair.
8. **Accepted as `discord-260726/ADR-D8`** — Provider-neutral refactoring boundaries
   for management, ingress, delivery, and generated API contracts.
9. **Accepted as `discord-260726/ADR-D9`** — Minimal deterministic
   Gateway/REST/interaction fixtures and essential E2E evidence requirements.

### Decision Point 1: Gateway ownership boundary

**Question**: Which runtime boundary should own one persistent Discord Gateway session
for each active customer-owned App connection?

**Affected requirements**:
`discord-260726/REQ-2`, `discord-260726/REQ-4`, `discord-260726/REQ-5`,
`discord-260726/REQ-10`, `discord-260726/REQ-13`, and `discord-260726/REQ-14`.

**Options**

- **A. Run Gateway sessions inside the existing general Agent Worker deployment.**
  Generalizes the current Slack Socket manager with the fewest new deployables and can
  call durable admission directly. However, unrelated Worker releases, scaling, and
  runtime load would churn all customer Gateway sessions, and high-cardinality sockets
  would share resources with Agent execution.
- **B. Add a dedicated Discord Gateway worker role that reuses Azents repository,
  credential, lease, and durable admission services.** One leased owner runs one
  active Gateway session per connection. The role is deployed and scaled separately
  from API and Agent Workers, decrypts credentials only while it owns the lease, admits
  raw events directly to PostgreSQL, and performs no routing, Session, approval, or
  delivery business transaction. This introduces a new process role but no additional
  callback relay or source of truth.
- **C. Restore the legacy lightweight standalone Gateway and forward signed callbacks
  to an internal API.** This maximally isolates Discord dependencies and can keep the
  protocol process small. For customer-owned Apps it also requires a new secure token
  distribution and lease-control protocol, adds an admission hop with its own retry
  loss modes, and duplicates authentication and fencing that the current repository
  already provides.

**Recommendation**: **B**. A dedicated Gateway worker role preserves the useful legacy
deployment isolation while using the current PostgreSQL lease and durable admission
boundaries directly. It should use one active session per connection, generation-fence
lease renewal and admission, stagger Identify attempts from each App's reported
session-start limits, retain explicit gap health, and support resumable session
checkpoints without making Gateway state canonical business state.

### Decision Point 2: Interaction ingress

**Question**: Should Discord commands, message actions, components, and modal submissions
arrive through Discord's outgoing HTTP interaction endpoint or through the leased
Gateway session?

**Affected requirements**:
`discord-260726/REQ-7`, `discord-260726/REQ-8`, `discord-260726/REQ-9`,
`discord-260726/REQ-11`, `discord-260726/REQ-13`, and `discord-260726/REQ-14`.

**Options**

- **A. Use a per-connection outgoing HTTP interaction endpoint.** Discord sends signed
  interactions directly to the API. Setup configures the App's endpoint URL through
  the Discord application API, and the endpoint uses an opaque connection selector plus
  the App public key to authenticate the raw request before durable admission. The API
  commits the bounded interaction and source-message projection before returning the
  initial response. Interaction tokens remain request-local capabilities used only for
  immediate or in-memory follow-up work.
- **B. Receive `INTERACTION_CREATE` through the Gateway worker.** This avoids configuring
  an HTTP endpoint, but interaction availability becomes coupled to the App's Gateway
  lease and reconnect state. The Gateway worker must also forward transient interaction
  tokens and coordinate the three-second acknowledgement deadline across its process
  boundary, expanding the worker beyond ordinary event admission.

**Recommendation**: **A**. Direct signed HTTP ingress keeps the three-second response
path inside the API transaction boundary, avoids relaying transient interaction tokens,
and leaves the dedicated Gateway worker responsible only for message dispatches that
cannot arrive through HTTP. Ordinary messages still use the Gateway; only interaction
delivery is configured for HTTP.

### Decision Point 3: Discord conversation and thread identity

**Question**: What Discord resource becomes the immutable External Channel conversation,
and when should Azents create or reuse a provider thread for an invocation that starts
from a channel message?

**Affected requirements**:
`discord-260726/REQ-7`, `discord-260726/REQ-9`, `discord-260726/REQ-10`,
`discord-260726/REQ-11`, `discord-260726/REQ-12`, and `discord-260726/REQ-13`.

**Options**

- **A. Create a provider thread immediately when the source interaction is admitted.**
  The thread establishes a visible route-neutral boundary before Agent selection. This
  reserves the source message's only thread early, but canceled selectors and invalid
  catalogs create orphan Discord threads that were never associated with an Agent.
- **B. Use one Discord thread as the canonical conversation and create or reconcile it
  only after a route is resolved.** A message action or App mention first durably
  retains the source and pending admission. Single routing, a valid channel default, or
  explicit Multi selection then fixes the route and commits deterministic thread
  provisioning before access continuation. An invocation already inside a thread uses
  that thread. A root message with an existing thread reuses only that exact thread; a
  root without one has a prospective thread ID equal to the source message ID, allowing
  an ambiguous create result to be reconciled without choosing another resource.
- **C. Require the participant to start a Discord thread before invoking an Agent.**
  This avoids provider thread creation and orphan provisioning, but adds a mandatory
  user step that has no Slack equivalent and prevents the confirmed message-action flow
  from starting directly from an ordinary eligible channel message.
- **D. Treat the parent channel as the conversation and keep replies in-channel.** This
  avoids thread creation but cannot isolate concurrent Agents or determine which later
  unmentioned channel messages belong to one immutable Agent Session.

**Recommendation**: **B**. A thread is the only provider-native resource that satisfies
immutable one-conversation routing and unmentioned continuation without absorbing an
entire channel. Deferring creation until the route is fixed avoids selector-cancellation
orphans while deterministic source-message identity makes create-versus-existing races
reconcilable. Existing binding or open-admission state always wins; a later selection
cannot replace it. Azents-created threads may use the selected Agent in their generated
name, while pre-existing user threads retain their existing name.

### Decision Point 4: Message Content intent and connection admission

**Question**: Is Discord `MESSAGE_CONTENT` an activation prerequisite for every
connection, and how should missing or revoked intent state affect setup, health, and
rollout?

**Affected requirements**:
`discord-260726/REQ-1`, `discord-260726/REQ-7`, `discord-260726/REQ-10`,
`discord-260726/REQ-14`, and `discord-260726/REQ-15`.

**Options**

- **A. Require verified Message Content capability before activation.** Setup checks
  the Discord application flags before opening a production lease and requires a
  successful Gateway Identify using the configured intent before marking the
  connection active. A missing flag leaves initial setup in `configuring`; a previously
  active connection that loses the capability or closes with Discord's disallowed
  intent code becomes `reconnect_required`. Routing and binding identity remain
  recorded but new execution fails closed until an administrator repairs and
  revalidates the App.
- **B. Allow a degraded mention-only connection without Message Content.** Message
  actions and explicit mentions can still expose content through Discord exceptions,
  but ordinary unmentioned thread continuation and attachment projection become
  unavailable. This creates a second product mode that contradicts the confirmed
  parity baseline.
- **C. Request the intent and rely only on live Gateway failure.** This keeps setup
  validation simple but discovers a deterministic configuration error after activation,
  produces avoidable connection churn, and gives administrators no preflight repair
  signal.

**Recommendation**: **A**. Message Content is not an optional enhancement because the
confirmed conversation contract requires unmentioned follow-up text and attachments.
Validation should accept either Discord's limited or approved Message Content
application flag as appropriate for the App, then require a live Gateway handshake.
Disallowed intent close code `4014` is non-retryable until configuration changes.
Discord creation remains rollout-gated until the dedicated Gateway worker, public
interaction callback base URL, capability validation, and deterministic provider
fixtures are enabled for the deployment.

### Decision Point 5: Control visibility and interaction UI

**Question**: Which Discord controls should be participant-private ephemeral
interactions, and which lifecycle state must be represented by durable ordinary
messages in the shared conversation?

**Affected requirements**:
`discord-260726/REQ-6`, `discord-260726/REQ-7`, `discord-260726/REQ-8`,
`discord-260726/REQ-9`, `discord-260726/REQ-11`, `discord-260726/REQ-13`,
and `discord-260726/REQ-14`.

**Options**

- **A. Make every control ephemeral.** Selectors and management remain private, but a
  Gateway-origin App mention cannot directly create an ephemeral response. Approval,
  Session navigation, and shared work state would also disappear from the thread or
  require transient interaction-token persistence.
- **B. Use a hybrid visibility boundary.** Message commands return a private ephemeral
  paged selector directly. An unresolved Gateway mention posts only one minimal durable
  selector-launch control next to the source; only its initiating principal may use it,
  and clicking it opens the same ephemeral selector. Approval controls, the one-time
  Session link, and current Channel Work are durable connection-owned messages in the
  resolved thread. Channel-default management returns an ephemeral opaque handoff to
  the authenticated Azents Web surface, which rechecks Workspace authority. Durable
  component controls contain only opaque scoped IDs; every click creates a new
  interaction and is revalidated against PostgreSQL state.
- **C. Make every selector and management control a durable public message.** This
  works for both Gateway messages and interaction commands, but exposes the complete
  Agent catalog and access labels to unrelated channel participants, permits confusing
  concurrent clicks, and creates avoidable channel clutter.

**Recommendation**: **B**. Private catalog and management state should remain
ephemeral, while shared conversation lifecycle state belongs in the thread. The
Gateway-mention launcher is the smallest necessary public bridge from a non-interaction
event to the private selector. Interaction tokens remain transient; durable controls
store provider message identity and opaque scoped action IDs only. Selection,
navigation, approval, and management always reload current connection, admission,
principal, route, and authorization state before mutation.

### Decision Point 6: Discord delivery and presentation bundles

**Question**: How should one canonical Agent reply or Channel Work snapshot be lowered
when Discord text, message-size, and upload limits require more than one provider
message?

**Affected requirements**:
`discord-260726/REQ-1`, `discord-260726/REQ-10`, `discord-260726/REQ-12`,
`discord-260726/REQ-14`, and `discord-260726/REQ-15`.

**Options**

- **A. Keep one provider message and truncate or reject content that does not fit.**
  This preserves the current singular progress identity and simple delivery model, but
  silently removes long replies, complete Channel Work details, or files accepted by
  the provider-neutral External Channel contract.
- **B. Lower each logical delivery to an ordered bot-owned provider message bundle.**
  The canonical action and all stable ordered part intents commit before any Discord
  call. Text is split on safe Markdown and code-block boundaries; each visible part
  begins with the bold Agent name or a bold Agent continuation label. Channel Work is
  one logical tracker projected across stable summary/task pages and updated or deleted
  by page identity. Files retain canonical order and are grouped into requests that
  satisfy both the configured External Channel limits and Discord's current request
  and per-file limits. Parts are attempted sequentially once, and the aggregate result
  remains partial, failed, or unknown unless every required part is confirmed.
- **C. Use per-Agent Discord webhooks to gain username and avatar overrides, then split
  content through webhook messages.** This improves visual impersonation but adds
  Manage Webhooks authority, separate webhook credentials and lifecycle, and a second
  provider identity that conflicts with the confirmed shared App bot identity.

**Recommendation**: **B**. Discord's provider limits must change delivery mechanics,
not canonical content or file policy. The shared App bot remains the message author;
every part visibly identifies the Agent in bold. A safe Agent image may appear only as
identity-neutral message decoration, such as an embed author icon, and otherwise falls
back to the App identity. Components, embeds, and ordinary content are presentation
details, while PostgreSQL owns the complete desired bundle, stable part ordinals,
provider message identities, and per-part outcomes. A final reply permits tracker
deletion only after all required reply parts are confirmed delivered.

### Decision Point 7: Credential, App identity, and installation cardinality

**Question**: What user-supplied credentials and provider identity define one Discord
connection, and may one customer-owned Discord App back more than one Azents
connection or target guild?

**Affected requirements**:
`discord-260726/REQ-2`, `discord-260726/REQ-3`, `discord-260726/REQ-4`,
`discord-260726/REQ-5`, `discord-260726/REQ-13`, and `discord-260726/REQ-14`.

**Options**

- **A. Use one Bot Token and one target Guild ID, with one App identity claimed by one
  current connection.** The encrypted credential contains only the Bot Token. Setup
  derives Application ID, public key, bot user ID, flags, and Gateway metadata from
  Discord; the Guild ID is non-secret configuration. The connection uses a fixed
  composite ingress profile: Gateway messages plus signed HTTP interactions. One App
  may have only one current Azents connection and one target guild, even if the bot is
  installed elsewhere. Token rotation must resolve to the same App and guild after
  first activation.
- **B. Require administrators to enter Bot Token, Application ID, public key, client
  secret, and Guild ID.** This makes every expected value explicit, but duplicates
  provider-authoritative identity, adds an unnecessary OAuth secret, and creates
  mismatch and rotation failure modes.
- **C. Introduce a shared Discord App aggregate with one Bot Token and multiple guild
  installation connections.** This can support one App across several servers without
  duplicate Gateway sessions, but requires a new credential root, tenant fan-out
  lifecycle, cross-installation endpoint ownership, and management model outside the
  confirmed one-App-to-one-server primary scenario.

**Recommendation**: **A**. Minimize secret input and derive provider identity from the
Bot Token. Setup generates the bot and `applications.commands` installation URL,
waits for membership in the declared guild, configures and verifies the per-connection
interaction endpoint, registers guild-scoped commands, validates Message Content, then
admits the Gateway lease. Application ID and Guild ID become immutable after first
activation; replacing a token is allowed only when Discord resolves it to the same
identity. A different App or guild requires a new connection. A current App-identity
claim is unique, while disconnected history retains its identity snapshot and releases
the current claim. Per-channel permission overwrites remain runtime capabilities and
are rechecked for each source, thread, and provider mutation.

### Decision Point 8: Provider-neutral extraction boundary

**Question**: Should Discord be implemented by copying the existing Slack orchestration,
by extracting explicit provider ports around the canonical External Channel domain, or
by creating a general dynamic integration plugin framework?

**Affected requirements**:
`discord-260726/REQ-1`, `discord-260726/REQ-2`, `discord-260726/REQ-3`,
`discord-260726/REQ-13`, `discord-260726/REQ-14`, and `discord-260726/REQ-15`.

**Options**

- **A. Add parallel Discord-specific services beside the current Slack services.**
  This minimizes initial refactoring, but duplicates connection lifecycle, admission,
  selection, access continuation, file policy, delivery outcome, and management rules.
  Security and parity fixes would need to be applied independently to both providers.
- **B. Extract explicit provider adapter ports while retaining one canonical
  orchestration domain.** Connection setup, routing, admission, selection, approval,
  binding, work, action, and delivery transactions remain shared. Explicit Slack and
  Discord adapters own credentials, provider validation, ingress authentication and
  normalization, Gateway protocol, resource provisioning and history, interaction
  presentation, file transfer, and provider delivery lowering. Adapters are registered
  explicitly by provider; there is no runtime plugin discovery or third-party SDK.
- **C. Build a general dynamic External Channel plugin framework.** This could support
  future providers without core changes, but requires a stable third-party lifecycle,
  schema, migration, security, and capability contract before the second provider has
  validated those abstractions.

**Recommendation**: **B**. Extract only the boundaries proven different by Slack and
Discord, and keep all authority-bearing state transitions in the existing canonical
services. Replace the assumption that one connection chooses exactly one `HTTP` or
`SOCKET` transport with an adapter-declared ingress profile: Slack retains its HTTP or
Socket choice, while Discord requires Gateway dispatch plus HTTP interactions. Use
tagged provider credential and configuration unions, an explicit provider registry,
and provider-neutral delivery bundles. Preserve existing Slack public behavior while
sharing management shells and adding provider-specific setup contracts through the
generated OpenAPI clients. Provider payloads, Discord components, Slack blocks, tokens,
and transport sessions never enter canonical routing or execution models.

### Decision Point 9: Deterministic and live verification boundary

**Question**: Which evidence is required in CI and before rollout to prove the Discord
Gateway, interaction, routing, approval, thread, delivery-bundle, and file contracts?

**Affected requirements**:
All requirements, with primary risk coverage for `discord-260726/REQ-7`,
`discord-260726/REQ-10`, `discord-260726/REQ-11`, `discord-260726/REQ-13`,
`discord-260726/REQ-14`, and `discord-260726/REQ-15`.

**Options**

- **A. Rely on unit and repository integration tests.** These can exhaustively cover
  transactions and races, but do not prove the public API, dedicated Gateway worker,
  raw signed callback, WebSocket, REST, multipart, Worker wake-up, and generated-client
  path together.
- **B. Require a minimal credential-free deterministic provider E2E suite.** A Discord
  fake exposes only the Gateway, signed-interaction, setup, thread, message, and file
  behavior needed by essential product journeys. Required CI drives product behavior
  through public/admin APIs and real worker processes without direct DB writes. Boundary
  permutations remain focused unit or integration tests rather than additional product
  E2E journeys.
- **C. Make live Discord E2E the primary required suite.** This verifies the actual
  platform but makes ordinary PR results depend on external credentials, mutable guild
  permissions, rate limits, command propagation, network health, and provider outages.

**Accepted direction**: **Modified B**. Required product E2E is limited to the essential
Single App conversation, Multi App primary scenario, and management/lifecycle safety
journeys, plus one compact Web-surface setup/repair journey covering the separate Agent
and Workspace entry points. The primary Multi journey includes one supported inbound
file and one explicit outbound file so file authority crosses the complete path once.
Focused unit, adapter integration, and Docker-backed repository tests cover catalog
pagination, signature tampering and expiry, Gateway lease takeover and Resume/gaps,
`4014`, permission loss, thread races, long-text splitting, maximum file batching,
rate limits, partial or unknown delivery, migration, lock order, generation fencing,
and recovery. No real Discord App, live guild, `live_external` test, external credential
prerequisite, or rollout certification is required or prepared for this snapshot.

## Decisions

### discord-260726/ADR-D1: Dedicated lease-fenced Discord Gateway worker role

**Decision**: Run customer-owned Discord Gateway sessions in a dedicated Discord
Gateway worker role that reuses Azents repository, credential, lease, and durable
admission services directly.

**Affected requirements**:
`discord-260726/REQ-2`, `discord-260726/REQ-4`, `discord-260726/REQ-5`,
`discord-260726/REQ-10`, `discord-260726/REQ-13`, and `discord-260726/REQ-14`.

**Consequences**:

- One generation-fenced lease owner runs one active Gateway session for each active
  Discord connection.
- The Gateway worker is deployed and scaled separately from API and Agent Worker
  processes so unrelated execution load and rollout do not share its lifecycle.
- The worker may decrypt a connection's bot token only while it owns the current lease.
- The worker admits bounded provider envelopes directly through the canonical External
  Channel admission service. It does not own route selection, access decisions, Agent
  Session creation, Channel Work, or provider delivery business transactions.
- Gateway Identify attempts are staggered using each App's reported session-start
  limits. Lease loss, credential generation changes, and terminal connection state
  fence further admission and close the provider session.
- Resumable Discord session checkpoints and explicit gap health are operational state;
  they never become canonical conversation or execution authority.

**Rejected alternatives**:

- Running Gateway sessions in the general Agent Worker was rejected because Worker
  rollout, scaling, and execution load would churn or contend with every customer
  connection.
- A standalone lightweight callback relay was rejected because customer-owned Apps
  would require a new credential-distribution and lease-control protocol plus another
  retry and authentication boundary before PostgreSQL admission.

### discord-260726/ADR-D2: Direct signed HTTP interaction ingress

**Decision**: Receive Discord commands, message application commands, components, and
modal submissions through a per-connection outgoing HTTP interaction endpoint rather
than through Gateway `INTERACTION_CREATE` events.

**Affected requirements**:
`discord-260726/REQ-7`, `discord-260726/REQ-8`, `discord-260726/REQ-9`,
`discord-260726/REQ-11`, `discord-260726/REQ-13`, and `discord-260726/REQ-14`.

**Consequences**:

- Setup configures the customer-owned App's interaction endpoint through the Discord
  application API and validates Discord's endpoint handshake.
- The public callback uses an opaque connection selector and the App's public key to
  authenticate the bounded raw request before trusting payload identity.
- The API durably admits the interaction and any required source-message projection
  before returning the initial Discord response within the provider deadline.
- Interaction tokens and equivalent callback capabilities remain request-local or
  in-memory-only. They are never persisted, logged, placed on a broker, or replayed as
  durable triggers.
- Ordinary message events remain Gateway-owned under `discord-260726/ADR-D1`; the HTTP
  interaction choice does not remove the dedicated Gateway worker.
- Interaction availability is independent from a temporary Gateway reconnect, while
  canonical routing, selection, approval, and execution still depend on current
  PostgreSQL connection and ownership state.

**Rejected alternative**:

- Gateway `INTERACTION_CREATE` delivery was rejected because it would couple every
  interactive control to Gateway lease health and require transient interaction tokens
  and the three-second response deadline to cross the dedicated worker boundary.

### discord-260726/ADR-D3: Route-resolved Discord thread conversation

**Decision**: Represent each Discord External Channel conversation as exactly one
Discord thread and create or reconcile that thread only after the Agent route is
resolved.

**Affected requirements**:
`discord-260726/REQ-7`, `discord-260726/REQ-9`, `discord-260726/REQ-10`,
`discord-260726/REQ-11`, `discord-260726/REQ-12`, and `discord-260726/REQ-13`.

**Consequences**:

- A message action or App mention first durably retains the source message,
  metadata-only attachments, principal, interaction, and route-neutral conversation
  admission without creating a provider thread.
- The Single route, valid Multi channel default, or explicit Multi selection fixes the
  route before thread provisioning and access continuation.
- An invocation inside an existing thread uses that exact thread. An invocation on a
  root message reuses only the thread already owned by that root, if present.
- For a root without a thread, the source message ID is also the prospective Discord
  thread ID. Provider create ambiguity is reconciled by fetching that deterministic
  resource rather than issuing an unbounded replacement mutation.
- Existing active binding or open admission state wins every race. A concurrent or
  later Agent choice cannot replace the recorded route or Session.
- Azents-generated thread names may identify the selected Agent. Existing user-created
  thread names are preserved.
- A thread that cannot be created, fetched, or used because of channel type,
  permissions, archival, locking, or provider rejection fails without binding or Agent
  execution and directs the participant to start another eligible conversation.

**Rejected alternatives**:

- Admission-time thread creation was rejected because canceled selectors and empty
  catalogs would leave provider conversations that never resolved to an Agent.
- Requiring the participant to create a thread first was rejected because it adds a
  mandatory step to the confirmed message-action scenario.
- Parent-channel binding was rejected because it cannot isolate concurrent immutable
  Agent conversations or classify later unmentioned messages safely.

### discord-260726/ADR-D4: Message Content as an activation prerequisite

**Decision**: Require verified Discord Message Content capability before any Single or
Multi App connection becomes active.

**Affected requirements**:
`discord-260726/REQ-1`, `discord-260726/REQ-7`, `discord-260726/REQ-10`,
`discord-260726/REQ-14`, and `discord-260726/REQ-15`.

**Consequences**:

- Setup requires the Discord application's limited or approved Message Content flag
  and a successful live Gateway Identify with the configured intent before activation.
- An initial connection without the capability remains `configuring` with an explicit
  repair action. It cannot route, bind, or execute an Agent.
- A previously active connection that loses the capability or receives Discord close
  code `4014` becomes `reconnect_required`. The dedicated Gateway worker does not retry
  until credential or provider configuration generation changes.
- Existing routes, channel defaults, resources, bindings, Agent IDs, and Session IDs
  remain durable history. New execution and provider mutation fail closed while the
  connection is unavailable.
- Message-command and explicit-mention exceptions do not create a reduced mention-only
  product mode because they cannot satisfy unmentioned continuation and file parity.
- Discord connection creation remains deployment-gated until the dedicated Gateway
  worker, public interaction callback base URL, capability validation, and
  deterministic Gateway/REST/interaction fixtures are enabled.

**Rejected alternatives**:

- A degraded mention-only mode was rejected because it would silently remove required
  follow-up and attachment behavior.
- Runtime-only detection was rejected because deterministic configuration errors must
  be visible before activation and must not cause repeated disallowed Identify attempts.

### discord-260726/ADR-D5: Hybrid private controls and durable thread state

**Decision**: Keep participant-specific Agent catalog and management interactions
ephemeral while representing shared conversation lifecycle through durable
connection-owned messages in the resolved Discord thread.

**Affected requirements**:
`discord-260726/REQ-6`, `discord-260726/REQ-7`, `discord-260726/REQ-8`,
`discord-260726/REQ-9`, `discord-260726/REQ-11`, `discord-260726/REQ-13`,
and `discord-260726/REQ-14`.

**Consequences**:

- A message application command returns a private ephemeral selector. Its current
  Agent catalog and access labels are loaded in bounded pages from canonical state.
- An unresolved App mention cannot return an ephemeral Gateway response, so it creates
  one minimal durable selector launcher next to the source. The launcher exposes no
  catalog or access state, only its initiating principal may use it, and its component
  opens the same private selector.
- Selection, cancellation, expiry, an existing binding, or terminal routing state
  deletes or terminalizes the public launcher through durable delivery state.
- Access approval controls, the one-time Session link, current Channel Work, explicit
  Agent replies, and lifecycle-unavailable notices are durable messages in the resolved
  thread.
- Channel-default management starts from a private Discord control and opens an opaque
  Azents Web handoff. The authenticated Web surface rechecks Workspace authority and
  handoff scope before reading or changing the default.
- Durable component messages persist provider message identities and opaque scoped
  action IDs only. Interaction tokens are never persisted, brokered, logged, or
  replayed.
- Every component callback reloads and validates connection, admission, initiating
  principal, route, expiry, current binding, and authorization state before mutation.

**Rejected alternatives**:

- An all-ephemeral design was rejected because Gateway message events cannot directly
  create ephemeral responses and shared lifecycle state must remain visible in the
  conversation.
- An all-public design was rejected because it would expose complete Agent catalogs and
  access labels, increase concurrent-actor ambiguity, and create unnecessary channel
  clutter.

### discord-260726/ADR-D6: Ordered bot-owned delivery bundles

**Decision**: Lower each canonical Discord reply and Channel Work projection to an
ordered bundle of one or more ordinary messages owned by the connection's shared App
bot.

**Affected requirements**:
`discord-260726/REQ-1`, `discord-260726/REQ-10`, `discord-260726/REQ-12`,
`discord-260726/REQ-14`, and `discord-260726/REQ-15`.

**Consequences**:

- The canonical action, complete provider-neutral desired state, stable part ordinals,
  and every provider delivery intent commit before the first Discord mutation.
- Long Markdown replies are split at safe text and code-block boundaries within current
  Discord limits. Every visible part begins with the bold Agent name or a bold
  continuation label.
- Channel Work remains one canonical work item and desired snapshot. Discord projects
  it through stable summary and task pages, updates only changed pages, and deletes
  obsolete pages by retained provider identity without truncating accepted canonical
  tasks, details, output, or sources.
- Up to 20 canonical outbound files retain their order and are grouped into provider
  requests that satisfy both configured External Channel limits and Discord's request
  and per-file limits. A known single-file provider-limit violation fails before the
  first provider mutation.
- Bundle parts are claimed and attempted sequentially once. The aggregate outcome is
  not delivered unless every required part is confirmed. Confirmed partial delivery,
  failed parts, and ambiguous parts remain visible and are not automatically replayed.
- A final reply permits Channel Work tracker deletion only after all required reply
  parts are confirmed delivered.
- The shared App bot remains the Discord author. Agent names are always bold visible
  content. A safe identity-neutral decorative image may be used when supported, but
  missing or rejected decoration falls back without affecting delivery.
- Provider message bundles and part outcomes require a provider-neutral extension to
  the current singular progress-message projection; provider payloads do not become
  canonical Channel Work state.

**Rejected alternatives**:

- Single-message truncation or rejection was rejected because provider mechanics must
  not silently remove content or files accepted by the canonical contract.
- Per-Agent Discord webhooks were rejected because they require separate credentials,
  permissions, lifecycle, and provider identities that conflict with the confirmed
  shared App bot model.

### discord-260726/ADR-D7: Derived single-App single-guild connection identity

**Decision**: Accept one Bot Token secret and one target Guild ID as setup input, derive
the authoritative Discord App identity from the provider, and allow one App identity to
back only one current Azents connection and one target guild.

**Affected requirements**:
`discord-260726/REQ-2`, `discord-260726/REQ-3`, `discord-260726/REQ-4`,
`discord-260726/REQ-5`, `discord-260726/REQ-13`, and `discord-260726/REQ-14`.

**Consequences**:

- The encrypted Discord credential payload contains the Bot Token only. Guild ID is
  non-secret provider configuration.
- Validation derives Application ID, public key, bot user ID, application flags,
  Gateway metadata, and current provider capability evidence from Discord. User-entered
  duplicates are not treated as authority.
- Discord uses one fixed composite ingress profile: Gateway dispatch events under
  `discord-260726/ADR-D1` plus signed HTTP interactions under
  `discord-260726/ADR-D2`. It is not exposed as a user-selected transport mode.
- One current App-identity claim may belong to only one connection and one target
  guild. Events observed for another guild are ignored and cannot resolve another
  Workspace or route.
- Setup generates the bot and `applications.commands` installation URL, waits for
  target-guild membership, configures and verifies the interaction endpoint, registers
  guild-scoped commands, validates Message Content, and completes a live Gateway
  handshake before activation.
- Application ID and Guild ID become immutable after first activation. Credential
  replacement is accepted only when the new Bot Token resolves to the same App, bot,
  and guild relationship. A different App or guild requires a new connection.
- Disconnected history retains its immutable provider identity snapshot while releasing
  the current App claim for a later connection.
- Required installation permissions are requested up front. Effective channel and
  thread permission overwrites are rechecked for each source admission, provisioning
  action, file operation, and delivery rather than projected as global authority.
- No OAuth client secret, OAuth access token, interaction token, or webhook credential
  is stored for this connection model.

**Rejected alternatives**:

- Manually entered Application ID, public key, and client secret were rejected because
  they duplicate provider-authoritative identity and add avoidable secret and mismatch
  failure modes.
- A multi-guild App aggregate was rejected because it introduces a new shared
  credential and installation ownership root outside the confirmed one-App-to-one-
  server scenario.

### discord-260726/ADR-D8: Explicit provider ports around canonical orchestration

**Decision**: Extract explicit provider adapter ports at the Slack/Discord boundaries
while retaining one canonical External Channel orchestration and persistence domain.

**Affected requirements**:
`discord-260726/REQ-1`, `discord-260726/REQ-2`, `discord-260726/REQ-3`,
`discord-260726/REQ-13`, `discord-260726/REQ-14`, and `discord-260726/REQ-15`.

**Consequences**:

- Connection lifecycle, route/default resolution, admission, principal and access
  policy, resource and message persistence, immutable binding, Agent Session creation,
  Channel Work, action commit, delivery claim/outcome, generation fencing, and
  lifecycle cleanup remain shared canonical services.
- Explicit Slack and Discord adapters own credential validation, provider identity and
  capability checks, ingress authentication and normalization, persistent Gateway
  protocol, resource provisioning and history, interaction presentation, file API
  operations, and provider delivery lowering.
- Provider adapters are registered explicitly by `ExternalChannelProvider` through
  dependency wiring. There is no dynamic discovery, external plugin ABI, or third-party
  provider SDK contract.
- The current assumption that one connection chooses exactly one `HTTP` or `SOCKET`
  transport is replaced by a provider-declared ingress profile. Slack preserves its
  HTTP or Socket choice; Discord has a fixed Gateway-dispatch plus HTTP-interaction
  profile.
- Credentials and setup configuration use tagged provider unions. Provider payloads,
  Slack blocks, Discord components, tokens, and transport sessions never enter
  canonical routing or execution models.
- Existing Slack public behavior is preserved while management shells, route
  projection, access, work, and lifecycle UI are shared. Provider-specific setup,
  capability, and repair contracts remain explicit.
- Public OpenAPI changes are the source for regenerated Python and TypeScript clients;
  generated files are never edited by hand.

**Rejected alternatives**:

- Parallel copied Discord orchestration was rejected because authority and idempotency
  fixes would drift across providers.
- A dynamic plugin framework was rejected because its external lifecycle, schema,
  migration, security, and capability contracts are not justified by the confirmed
  two-provider scope.

### discord-260726/ADR-D9: Essential deterministic E2E without live Discord

**Decision**: Require a small credential-free deterministic Discord provider suite and
essential product E2E journeys only. Do not add live Discord verification or external
Discord prerequisites to this snapshot.

**Affected requirements**:
All requirements, with end-to-end focus on `discord-260726/REQ-2`,
`discord-260726/REQ-4`, `discord-260726/REQ-5`, `discord-260726/REQ-7`,
`discord-260726/REQ-10`, `discord-260726/REQ-11`, `discord-260726/REQ-13`,
and `discord-260726/REQ-15`.

**Required E2E journeys**:

1. **Single App core conversation** — Agent-admin setup and activation, sole-route
   invocation, route-resolved thread creation, access continuation, one immutable
   binding and Session, one unmentioned follow-up, and one explicit reply.
2. **Multi App primary scenario** — Workspace-admin setup, two available Agents,
   message application command, private selector, access-required selection, retained
   source with one inbound file, approval, duplicate callback convergence, one binding,
   later continuation, and one explicit reply with one outbound file.
3. **Management and lifecycle safety** — channel default creation, default-based future
   routing, route removal and default invalidation without existing-binding reroute,
   and terminal idempotent disconnect.
4. **Compact Web-surface setup and repair** — separate Agent Single and Workspace Multi
   entry points, secret redaction, configuring/reconnect guidance, and authority
   boundaries in one bounded browser journey.

**Focused non-E2E coverage**:

- Unit and adapter integration tests own more-than-25-Agent pagination, signed callback
  tampering and expiry, Gateway lease takeover, Resume and gap behavior, close code
  `4014`, permission loss, thread create ambiguity and races, Markdown splitting,
  maximum file batching, rate limits, and partial or unknown delivery.
- Docker-backed repository and migration tests own schema preservation, unique App
  claims, lock order, generation fencing, idempotency, and recovery.
- The deterministic fake records operation names, provider identities, part ordinals,
  sizes, acknowledgements, and outcomes only. It never retains Bot Tokens, interaction
  tokens, participant message bodies, or file bodies in exported evidence.

**Excluded verification**:

- No real Discord App or test guild is provisioned.
- No Discord credential or `live_external` prerequisite is added.
- No live certification gates implementation or rollout in this snapshot.

**Rejected alternatives**:

- Unit-only verification was rejected because it cannot prove the public API,
  dedicated Gateway worker, signed callback, worker wake-up, generated-client, and
  provider delivery path together.
- Live-primary verification was rejected because the current environment does not have
  the required Discord App and guild setup, and external state would make required CI
  nondeterministic.
