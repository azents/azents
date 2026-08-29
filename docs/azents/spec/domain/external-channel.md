---
title: "External Channel"
created: 2026-07-22
tags: [backend, frontend, external-channel, slack, discord, security]
spec_type: domain
domain: external-channel
owner: "@Hardtack"
code_paths:
  - python/apps/azents/db-schemas/rdb/migrations/versions/*external_channel*.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/*channel_work*.py
  - python/apps/azents/src/azents/core/external_channel.py
  - python/apps/azents/src/azents/core/external_channel_file.py
  - python/apps/azents/src/azents/core/external_channel_projection.py
  - python/apps/azents/src/azents/core/external_channel_progress.py
  - python/apps/azents/src/azents/core/external_channel_reference.py
  - python/apps/azents/src/azents/core/external_channel_session_presence.py
  - python/apps/azents/src/azents/core/external_channel_title.py
  - python/apps/azents/src/azents/core/slack_external_channel_progress.py
  - python/apps/azents/src/azents/core/enums.py
  - python/apps/azents/src/azents/engine/events/external_channel_rendering.py
  - python/apps/azents/src/azents/rdb/models/external_channel.py
  - python/apps/azents/src/azents/rdb/models/external_channel_ingress.py
  - python/apps/azents/src/azents/repos/external_channel/**
  - python/apps/azents/src/azents/services/external_channel/**
  - python/apps/azents/src/azents/job_runtime/**
  - python/apps/azents/src/azents/api/testenv/external_channel_ingress/**
  - python/apps/azents/src/azents/cli/external_channel_ingress.py
  - python/apps/azents/src/azents/services/session_title.py
  - python/apps/azents/src/azents/broker/types.py
  - python/apps/azents/src/azents/worker/session/**
  - python/apps/azents/src/azents/services/root_agent_session_creation/**
  - python/apps/azents/src/azents/repos/agent_automatic_project/**
  - python/apps/azents/src/azents/api/public/external_channel/**
  - python/apps/azents/specs/public/openapi.json
  - python/libs/azents-public-client/src/azentspublicclient/api/external_channel_v1_api.py
  - python/libs/azents-public-client/src/azentspublicclient/models/external_channel_*.py
  - python/libs/azents-public-client/src/azentspublicclient/models/managed_*.py
  - typescript/apps/azents-web/src/features/external-channel-approval/**
  - typescript/apps/azents-web/src/features/external-channel-management/**
  - typescript/apps/azents-web/src/features/external-channel-workspace/**
  - typescript/apps/azents-web/src/features/session-channels/**
  - typescript/apps/azents-web/src/app/(app)/w/[handle]/(workspace)/integrations/slack/**
  - typescript/apps/azents-web/src/features/agents/components/AgentSessionHeader.tsx
  - typescript/apps/azents-web/src/features/agents/components/AgentSessionHeader.module.css
  - typescript/apps/azents-web/src/features/chat/components/ExternalChannelMessage.tsx
  - typescript/apps/azents-web/src/features/chat/externalChannelMessage.ts
  - typescript/apps/azents-web/src/trpc/routers/externalChannel.ts
api_routes:
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/default-response-mode
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/manifest
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/slack
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/slack
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/discord
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels/{connection_id}/discord
  - /external-channel/v1/workspaces/{handle}/external-channels/slack/multi
  - /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}
  - /external-channel/v1/workspaces/{handle}/external-channels/discord/multi
  - /external-channel/v1/workspaces/{handle}/external-channels/discord/multi/{connection_id}
  - /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/agents
  - /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/{connection_id}/channel-defaults
  - /external-channel/v1/workspaces/{handle}/external-channels/slack/multi/management-handoffs/{handoff_id}
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}/external-channels/{binding_id}/response-mode
  - /external-channel/v1/approval-requests/{access_request_id}
last_verified_at: 2026-08-29
spec_version: 64
---

# External Channel

## Overview

External Channels connect provider conversations to Azents Agents without treating provider credentials, conversations, participants, or delivery state as AgentSession-owned chat data. Workspace owns connection credentials and provider identity. An Agent route selects the Agent for a connection. A channel participation setting selects whether top-level traffic shares one parent-channel conversation or creates isolated thread conversations. A resource represents one provider conversation, and a connected binding links that resource to one AgentSession until explicit disconnect.

Slack and Discord are supported providers. A Slack connection uses a manually
configured Slack App and selects either signed HTTP callbacks or Socket Mode. A Discord
connection uses a customer-owned Discord App, its Bot Token, one target Guild, a signed
interaction callback, and a Gateway session. A provider-neutral External Channel
Gateway runtime owns both Slack Socket Mode and Discord Gateway connections. Both
providers have an immutable App mode. A Single App is managed by one Agent's
administrators and has exactly one
Agent route. A Multi App is managed by Workspace Owners and Managers and may have zero
or more Agent routes. One Agent may appear in several Apps, and one AgentSession may
contain multiple independent bindings.

## Ownership and Security Boundaries

- Connection and route records are Workspace/Agent administration state.
- Provider resources, principals, conversation positions, access requests, and
  selector interactions retain only routing, authorization, and replay identity.
- Bindings are Session lifecycle resources. Each binding's current or latest Channel
  Work cycle and Work-owned provider projection parts are one Session-bound Toolkit
  State value under `external_channel/channel_work:{binding_id}`.
- Credentials are encrypted at rest and decrypted only inside provider adapters. Public APIs, generated clients, prompts, events, logs, UI state, and test evidence expose only redacted credential status.
- Provider history is the inbound content authority. A callback admits only a
  content-free active ingress identity. One resolved history range becomes independent
  canonical mailbox rows, one per provider message, and then contiguous Session events
  with provider, resource, sender, author type, `prompt_role`, and message identity
  attribution.
- Bounded Slack and Discord provider projections are decoded and encoded through
  Azents-owned typed contracts at the durable JSON boundary. SDK objects, signed raw
  bodies, SDK private state, and Gateway frames remain process-local and are never
  reconstructed or persisted for replay.
- Public `slack-sdk` APIs own supported Slack operations. Discord REST operations use
  one pinned `discord.py` Client lifecycle and preserve its authenticated aiohttp
  session and rate-limit state across each caller-owned multi-operation workflow.
  Supported REST calls are isolated behind one bounded adapter over that Client's
  private HTTP client; raw payloads are validated into Azents-owned typed contracts.
  Direct provider transport is closed to six gaps only: Discord current-Application
  Interaction Endpoint configuration, Discord individual Guild command create,
  Discord multipart file-message create, Discord CDN attachment bytes, Slack
  private-file bytes, and Slack external-upload bytes. The callback gap is removed
  when the adopted public `discord.py` API can transmit the endpoint field correctly.
  Static repository checks permit private Discord HTTP use only in the pinned adapter
  and reject other private Discord SDK imports, second Discord SDKs, SDK-global
  endpoint mutation, and provider HTTP outside the direct-transport allowlist.
- Slack and Discord model input preserves provider-native user and channel reference
  tokens in the source body. Resolved display names appear separately after the message
  batch in one XML provider-reference mapping block, so readability enrichment does not
  remove tokens that an explicit Channel action can reuse.
- An ExternalChannelPrincipal is provider provenance and admission authority only. It is never an
  Azents execution User. After a binding releases durable work, the linked Team Session executes
  through canonical Session/Run authority without inferring a User from the principal, approver,
  route owner, Agent creator, Workspace owner, or broker signal.
- External Channel wake-ups are routing-only `SessionWakeUp(session_id)` notifications.
  A non-empty processing batch sends one wake after its mailbox rows commit. Pending
  canonical mailbox input and the existing Session recovery path are wake-recovery
  authority; provider content is never carried by the broker.
- Unfinished Channel Work uses the dedicated
  `external_channel_continuation` hook input, mailbox kind, event kind, model
  reminder, public projection, and UI presentation. It never reuses
  `goal_continuation`, so active Goal state cannot reinterpret or recursively
  re-trigger Channel work.
- Promoted `external_channel_continuation` input carries an ephemeral set of its active
  binding IDs. Client-tool-result follow-up preserves that set until a new actionable
  input boundary replaces it. Initial External Channel invocation and every
  non-continuation or mixed boundary carry no silent-completion authority. Eligibility
  is never inferred by searching transcript history or from an active binding alone.
- Foreign keys are restrictive across lifecycle roots. AgentSession deletion cannot cascade away provider or audit roots before lifecycle cleanup and verification complete.

## Core Records

| Record | Current contract |
| --- | --- |
| Connection | Workspace-owned provider App identity, immutable `single` or `multi` mode, encrypted credentials, capability/health snapshot, configuration and App-claim generations, terminal disconnect state, and provider ingress lease/gap state. Slack has one selected HTTP or Socket transport. Discord concurrently uses signed HTTP interactions and a Gateway session, and its typed non-secret configuration owns the target Guild plus the required new-Thread automatic archive duration. |
| Agent route | Persistent connection-to-Agent relationship. Single Apps require exactly one current route. Multi Apps retain zero or more available or removed catalog routes; immutable Agent identity snapshots preserve history after Agent deletion. Each active dedicated route defaults to open human access and separately defaults to rejecting external bot messages. |
| Channel default | Multi App channel-to-route preference with exactly one Azents User or provider-principal configuration actor. At most one active default exists per connection and provider parent channel. Replacement or clear terminalizes the old route's parent binding and invalidates its participation setting and pending setup claim rather than silently retargeting them. |
| Participation setting | One active `channel` or `threads` location and concrete response-mode default for the connection and provider parent channel's selected route. The setting has a generation, exactly one User-or-principal latest actor, and terminal invalidation evidence. It is never inferred from an existing binding. |
| Setup claim | One bounded nonterminal channel-setup authority retaining the latest eligible explicit mention's content-free source Resource, principal, position/replay boundary, source revision, selected route/location state, and expiry. It creates no Binding, Session, mailbox input, or AgentRun before location selection. |
| Interaction | Idempotent signed Slack or Discord shortcut, command, component/action, navigation, or submission claim. An interaction may bind to a setup claim, setting generation, or connected Binding while provider trigger IDs, Discord interaction tokens, callback URLs, signatures, and raw bodies remain transient. |
| Resource | One provider conversation. `parent_channel` uses the stable provider parent-channel identity and delivers directly there. Thread Resources use a Slack root message or Discord root/existing thread and may retain a provisioned Discord delivery-thread identity. A directly and unambiguously created Discord delivery thread additionally retains its exact normalized provisional name as optional one-shot initial-title evidence. Scope is explicit in type and labels and is never inferred from a missing thread field. |
| Conversation position | Durable read-through position for one connection-scoped parent channel or thread. PostgreSQL position compare-and-set is the ordering authority across retries and replicas. |
| Principal | Provider tenant/user identity and author category. It is not an Azents User or WorkspaceUser. |
| Binding | Persistent link from one route/resource to one AgentSession with one required concrete `mention_only` or `all_messages` response mode. `disconnected_at IS NULL` identifies the current connected relationship; a non-null timestamp is its terminal boundary. Configured parent/thread creation copies the active participation setting; legacy isolated-thread access replay without a setup claim copies the Agent default. Binding, real Session, initial Channel Work, and the first content-free ingress item commit together only after setup selection or for an already configured conversation. |
| Ingress conversation owner and item | One active owner is unique for the effective target Resource and owns the lease, provider-conversation preparation state, nullable resulting Binding/Session, first-batch flag, and current processing-batch fence. Each active item retains a content-free physical source locator and position, immutable owner authority, queue order, attempt/original-age state, processing ownership, the exact admitted trigger correlation, and the bounded count of files observed in a live Slack or Discord callback. Its provider-native explicit-invocation flag remains separate response-mode and provider-control evidence; an ordinary message admitted by a connected `all_messages` Binding still owns an active trigger correlation. Slack `location=channel` may fan source threads into one parent owner. Discord parent-channel messages use the parent owner, while every existing Discord Thread keeps an exact independent owner and participation state. Parent participation can select the routed Agent and the response mode copied after an explicit Thread invocation, but it never makes an unbound Thread participate. A required Discord delivery thread is prepared before the owner records a new Binding and Session. The first ready claim is one item and later claims are at most ten. Successful, suppressed, terminal provisioning, and bounded-failure rows are deleted; no completed outcome, tombstone, generic job, or durable wake row exists. |
| Mailbox item and Session events | Every canonical provider message uses one deterministic `external_channel_message` mailbox row with one `prompt_role = context | invocation`, provider-message idempotency identity, and explicit order group/sequence. Every active admitted item correlates its exact eligible human trigger row to `prompt_role=invocation`, including an ordinary connected `all_messages` trigger whose provider-native explicit-invocation flag is false; other retained history remains `context` unless it independently matches another active admitted trigger. PostgreSQL conversation-position compare-and-set is the duplicate-prevention and ordering authority. Pending mailbox state owns wake recovery. Only the exact eligible human invocation-role row created with the root Session may carry transient initial-title eligibility; promotion and mailbox deletion consume it. Promotion creates canonical External Channel Session events; no parallel provider-message, revision, invocation-batch, activation, title-attempt, or wake-dispatch record exists. |
| Access request/grant/block | Opaque approval request with a content-free provider locator and conversation-position replay boundary, Session- or Agent-scoped grant, and Agent-scoped block for one external principal. Final decisions retain their authorization result independently from post-commit approval-control cleanup. |
| Channel Work and provider projection | One binding-specific Session-bound Toolkit State value contains the current or latest work-cycle identity, status, title, ordered provider-neutral tasks with stable identities, desired snapshot and revisions, finish timestamp, and ordered current provider projection parts. Projection parts retain only the desired revision, provider identity, and projection status required for later update or deletion. Whole-state optimistic concurrency is independent per binding. Agent-requested publication executes through the ordinary Tool call/result history with process-local effect plans and no separate Action or delivery history. |

## State Invariants

- Connection status owns provider ingress and credential health: it may be `configuring`, `active`, `degraded`, `reconnect_required`, `disconnecting`, or `disconnected`; disconnect is terminal and does not silently fall back to another transport.
- App mode is immutable. Existing dedicated connections are Single Apps. Single Apps
  have exactly one route and association removal disconnects the App. Multi Apps may
  have zero or more routes; catalog removal is durable history and can be explicitly
  re-enabled while the rollout gate permits growth.
- Provider health and reconnect do not rewrite route catalog state. New execution
  requires a locked `active` or `degraded` connection, an available route, and active
  Agent lifecycle.
- Slack Web API operations use public high-level `slack_sdk.AsyncWebClient` methods
  with SDK retry handlers disabled, so each provider mutation remains one attempt.
  Direct HTTP is limited to authenticated private-file streaming and presigned upload
  bodies. Dedicated non-propagating SDK loggers prevent provider request and response
  content from entering application diagnostics.
- Slack Socket Mode uses the public aiohttp `SocketModeClient` with SDK automatic
  reconnect enabled. The SDK owns endpoint acquisition and replacement, WebSocket
  establishment, Ping/Pong, stale-session detection, frame receipt, queue dispatch,
  and recoverable reconnect. Azents owns the fenced lease, DB-only durable
  admission, acknowledgement ordering, typed lifecycle projection, and bounded
  terminal health classification. Public SDK Socket Mode request and response types
  validate envelopes and construct acknowledgements.
- An exact connected thread binding resolves before parent-channel participation.
  Otherwise the Single App route or valid Multi App channel default selects one Agent,
  and the active participation setting selects `channel` or `threads`. An explicit
  eligible top-level invocation with no setting creates or replaces one setup claim;
  ordinary messages create no setup state. No path chooses an arbitrary route or fans
  out to several Agents.
- One active participation setting and one nonterminal setup claim may exist per
  connection and provider parent channel. A later eligible explicit mention replaces
  the pending claim's source and increments its revision. The first valid location
  selection freezes the latest revision and releases exactly one canonical continuation.
- Durable execution mutations are fenced by the current Session owner generation.
  Provider principals, Slack callback actors, Workspace requesters, and approvers
  remain provenance or authorization identities and never become the execution User.
- A resource is `active`, `unavailable`, or `deleted`. Provider history is read on
  demand by a leased Session drain after durable callback admission and has no durable
  hydration lifecycle. When a live callback observed files but the provider-history
  trigger snapshot exposes fewer bounded file entries, the item remains a temporary
  history failure and follows the existing ingress retry and age limits.
- A binding has no active/inactive lifecycle state. `disconnected_at IS NULL` means
  connected, and explicit disconnect sets the terminal timestamp and reason. Gateway
  health, lease ownership, reconnect state, and provider-ingress availability never
  reactivate or disable that relationship.
- A binding response mode is always concrete. `all_messages` admits eligible ordinary
  human messages on a connected binding; `mention_only` requires an explicit provider
  invocation. Creating every Binding requires an explicit invocation regardless of the
  configured location or response-mode default. Parent-channel and Discord Thread
  participation are independent: a parent Binding never authorizes ordinary traffic in
  an unbound Thread. Location selection snapshots the Agent
  default into the participation setting. Later configured Bindings copy that setting,
  while existing Bindings retain their own mode. Existing Agents and historical
  bindings use `all_messages`.
- Every model input boundary exposes `channel_action ignore` beside `finish` and
  `continue`. `ignore` accepts no publication or Work-update fields and uses the same
  active Session, Agent, binding, route, connection, and resource validation as other
  Channel Actions. It finishes existing active Work regardless of recorded task
  status: desired progress is cleared, current provider projection observation is
  retained until its outcome settles, and each current `PRESENT` Activity Tracker for
  only that binding receives one post-commit deletion effect. No reply, progress
  create/update, file, or unrelated provider effect is planned.
- Connection capabilities expose `download_files` and `upload_files` independently.
  Missing legacy fields are unavailable. A model-visible file key directly contains
  its provider request coordinates. It is valid only for the current Agent, Session,
  connected binding, route, current credentials, and directional capability. Transient
  Gateway or Socket health is not outbound authority; provider authentication and
  authorization remain authoritative at download time.
- File-bearing External Channel state retains provider metadata and direct
  provider-address keys only. Provider bodies enter the common Server-to-Runtime transfer path only
  after a current authorization recheck. Runtime bodies leave through one verified
  Runtime-to-provider transfer per source during the current Tool execution. Runtime
  transfer services are required Runtime infrastructure, not connection capabilities,
  and wait for the current Runtime only when the Tool executes. Runtime transfer claims
  follow their existing bounded coordinator lifecycle. No External
  Channel row, event, prompt, or queue payload stores transfer bytes, provider upload
  URLs, object-store credentials, object keys, trusted object handles, or a provider
  operation history.
- A Discord connection is scoped to its validated Application and target Guild. The
  callback selector is opaque and retained only as a hash; the Application public key,
  Bot identity, and required Guild Message Command identifier are
  configuration-derived state. Discord
  interaction tokens, callback URLs, raw interaction bodies, and signature values are
  never durable External Channel state.
- The External Channel Gateway's Discord manager claims each connection through owner,
  configuration-generation, App-claim-generation, and lease-generation fences.
  Heartbeats and lease renewal do not authorize durable mutation by themselves.
  The manager uses only public high-level `discord.py` APIs and typed SDK callbacks.
  The SDK owns discovery, heartbeat, reconnect, and in-process Resume. Azents neither
  reads raw Gateway payloads/private SDK state nor persists a cross-process Gateway
  Resume checkpoint. Durable provider-event idempotency and the current
  lease/configuration/App-claim fence protect canonical admission.
- Discord `ready`, `resumed`, and `disconnect` callbacks update active or degraded
  health only through the current lease fence. Slack Socket establishment and endpoint
  replacement callbacks use the equivalent fenced active/gap transitions. One
  provider-neutral gateway process supervises both required manager loops and exits if
  either loop stops unexpectedly. One customer configuration requiring reconnection
  remains connection-local health. General Agent Workers own neither provider socket.
- Production Discord Gateway endpoint selection belongs to `discord.py`; Azents does
  not expose a custom or insecure Gateway endpoint override.
- Inbound Slack and Discord attachments retain bounded identifiers, filename, media
  type, and optional advisory provider size in durable state. Missing, malformed, or
  stale provider size does not make an otherwise supported hosted attachment
  unavailable, and `download_external_file` accepts no caller-selected size.
- The trusted provider adapter refreshes current identity and authorization metadata,
  uses only the authenticated final download URL's HTTP `Content-Length` as the
  declared transfer size and policy input, streams and counts the response body, and
  stages an immutable verified object before Runtime delivery. The GET response
  declaration and body must match that size exactly; excess bytes terminate streaming
  and an early end fails without a Runtime destination commit. Provider URLs and bytes
  remain outside durable External Channel state.
- Selected setup replay or configured binding acceptance atomically commits the
  Binding, real Session, initial Channel Work, and first content-free ingress item.
  Provider history, per-message mailbox admission, cursor advancement, and the running
  transition occur later in the leased Session drain. A non-empty processing batch
  sends one post-commit broker wake; failure leaves canonical mailbox input
  recoverable. Process-local joined-presence and initial-progress plans remain
  independent controls. Failed, unknown, cancelled, or interrupted presence or
  progress effects never block mailbox promotion, Session wake, or AgentRun creation
  and create no recovery work. Slack lowers work through its
  retained Tracker message; Discord lowers each work snapshot to one retained compact
  Embed Tracker. The Embed title carries the current-work title, while its bounded
  description carries the status summary, every ordered task title and status marker,
  then prioritized details, output, and labeled sources. The functional Tracker body is
  not duplicated as ordinary message content; Multi App Agent attribution remains
  separate readable content. Every initial and updated Tracker also carries one
  provider-native `View session` control. The provider delivery boundary derives its
  canonical Agent Session URL from the current Workspace, Agent, and Session target;
  Channel Work and projection state retain neither the URL nor provider component.
  A parent-channel Resource posts directly to the Slack or Discord parent channel. A
  Discord thread Resource provisions or reuses one delivery thread, persists that
  target, and sends approval controls, Session navigation, replies, files, progress,
  and cleanup to that thread. A delivered final answer permits active-progress
  deletion, and separate work cycles never share provider identities.
- A newly created External Channel root Session uses only the exact eligible human
  mailbox event whose `prompt_role` is `invocation` for the existing two-phase automatic title
  lifecycle. The title model receives prompt-only guidance to ignore Bot or App markup
  used only to address the Agent while preserving request-relevant references; canonical
  provider content, reference evidence, and deterministic initial-title input remain
  unchanged. Saved lightweight-model Structured Output capability selects the same
  tri-state response-envelope behavior used by ordinary Sessions without changing the
  selected provider integration or model. Session admission, wake, AgentRun creation,
  and ordinary provider effects do not wait for title generation. After the matching `auto_initial` to
  `auto_generated` title commit, Discord performs one best-effort operation only for a
  directly created eligible thread: revalidate current lifecycle authority, read the
  thread once, and send at most one name-only update when the current name still equals
  the retained provisional name. Existing, ambiguously recovered, human-renamed,
  disconnected, unavailable, or otherwise invalid targets are not mutated. Slack has no
  provider-title projection. Failure or interruption creates no retry, reconciliation,
  backfill, attempt record, or execution gate.
- The Tracker uses one native read-only Slack task card before Channel Work is
  declared. Once tasks exist, one native Slack plan carries the Agent-authored
  current-work title and up to 49 ordered tasks. Canonical task states are
  `pending`, `in_progress`, `completed`, and `failed`; Slack lowers them to
  `pending`, `in_progress`, `complete`, and `error`. Nested Plan tasks omit a
  standalone block `type` and may contain literal rich-text details/output and
  labeled HTTP or HTTPS sources. The payload sends no Slack `plan_id`.
- Channel Work desired state is a versioned provider-neutral complete snapshot.
  The canonical payload is schema version `1` Toolkit State at
  `external_channel/channel_work:{binding_id}` and retains a stable
  `work_cycle_id` across progress rendering and provider-effect settlement.
  A serialized desired snapshot is limited to 64 KiB and is rejected atomically
  before canonical state changes when it exceeds that bound.
  Slack-specific blocks and revision-derived `block_id` values are created only
  at the provider presentation boundary. Slack streaming is not used; retained
  `chat.postMessage` and `chat.update` mutations apply complete snapshots.
- Confirmed deletion clears only the matching Tracker identity. It does not create a
  replacement or catch-up effect. A later explicit progress transition may create a
  new Tracker from the then-current desired state. Finished work never recreates a
  Tracker, and a missing delete target is already absent.
- Inbound message-create snapshots are immutable. Provider edit and delete callbacks
  are excluded; they do not create lifecycle corrections or rewrite already accepted
  Session input.
- Trigger eligibility is evaluated independently from provider-visible context.
  Only humans may invoke according to route access policy. Bot, app, and system
  callbacks never trigger execution or consume a conversation read position. The
  connected Azents bot is excluded from provider-history projection to prevent loops,
  while other visible humans, bots, and system authors remain contextual input for a
  later eligible human trigger.
- Discord inbound and REST-history projection retains bounded embed title,
  description, author/footer text, fields, and image/thumbnail presence alongside
  visible message and file metadata. Raw provider payloads and embed, CDN, proxy, and
  profile URLs are not persisted or shown to the model.
- A Session- or Agent-scoped grant authorizes invocation only for the same Agent, principal, route relationship, and active resource. Blocks take precedence.
- Creating a new binding Session snapshots the routed Agent's current automatic
  Project policy into the root `SessionAgentContext` in the same transaction as
  Session and binding creation. This applies to selected setup replay, configured
  ingestion, and legacy isolated-thread Allow replay. A setup-linked Allow commits
  authorization and resumes location setup without creating a Binding or Session.
  Reusing an existing binding keeps its existing Session/context
  Project snapshot; later policy changes are not retroactive.
- Restore never reactivates a disconnected binding, ended work item, or connection.

## Management Surface

Agent administrators manage Single Apps from Agent settings. They can retrieve a
complete copy-ready Slack App Manifest, follow equivalent manual Slack UI
instructions, create the App and its sole route, validate it, replace its App ID,
transport, and complete credential set, disconnect it terminally, and manage grants
and blocks. The active dedicated route management operation controls
`open_access_enabled`: humans are open by default, and no bot, app, or system author
can invoke. This setting never overrides a block or admits the connected Azents bot.
Removing the Single association disconnects the App. Secret fields remain blank and
required when an existing connection is edited.

Each Single App connection card labels its validated capability snapshot as channel
permissions. The card shows only granted and missing counts; a detail modal separates
the two sets and explains every permission in user-facing terms. Missing Slack
permissions identify the relevant optional scope when known and direct the
administrator to add scopes, reinstall the App, and validate again. Missing Discord
permissions direct the administrator to check the Bot installation and server
permissions before validating again. A connection without a capability snapshot
instead directs the administrator to run validation.

The same Agent settings surface exposes the Agent's default External Channel response
mode even when no App is connected. Agent administrators may replace the required
`mention_only` or `all_messages` value. The mutation changes only the value copied
into a later participation setting or legacy isolated-thread Binding; it does not
enumerate or rewrite active settings or existing bindings.

Workspace Owners and Managers manage provider-scoped Multi Apps from Workspace
integrations. Ordinary Members have neither Multi read nor write authority. Slack and
Discord Multi creation start with zero Agents. Their provider-correct public API,
generated clients, tRPC, and Workspace UI support paged connection and route catalogs,
idempotent Agent association, removed-route re-enable, channel defaults, validation
and complete credential replacement, impact previews, and generation-fenced route
removal/default mutation/App disconnect. Disconnected Multi Apps remain readable
historical records but accept no further mutation.

Discord Single and Multi management also expose a connection-wide Thread automatic
archive duration of 60, 1440, 4320, or 10080 minutes. New and migrated connections use
1440. A dedicated non-secret mutation changes only this typed provider configuration,
preserving credentials, callback and Gateway authority, health, routes, Bindings, and
Sessions. Agent settings keep associated Workspace Multi Apps read-only; their policy
is managed only from Workspace integrations.

Provider-native Multi setup may create the first channel default with provider-principal
provenance after showing only routes that principal may invoke. Web replacement or
clear remains a Workspace Owner/Manager action. Both use the same old-route transition:
invalidate the participation setting and setup claim, disconnect only the connected
parent binding, preserve every thread binding and Session, and report those impacts.

Agent settings show associated Multi Apps as Workspace-managed read-only context.
Slack can open an opaque, expiring management handoff for the current Multi App
channel; the authenticated Web surface rechecks Workspace write permission and
handoff scope before reading or replacing that channel's default.

Discord Single and Multi setup use separate Agent and Workspace flows. A connection
validates that its Bot Token belongs to the submitted Discord Application, retains the
target Guild identity, durably prepares the opaque callback selector hash and
Application public key behind the current credential and configuration-generation
fences, then configures the signed-interaction callback and reconciles the required
Guild-scoped invocation and conversation-settings command set. Reconciliation creates
or updates required Azents-owned commands, removes only recognized obsolete Azents
variants, preserves unrelated customer commands, and stores the validated role-to-ID
map. This preparation accepts only
Discord PING verification; ordinary interactions remain unauthorized until the
activation commit. A failed provider registration clears the provisional callback
authority behind the same fences and requires reconnection. Replacing Discord
credentials or App identity invalidates prior callback and Gateway authority before
activation repeats. Dedicated Discord setup is available without a deployment-scoped
provider rollout flag; Discord Multi App creation is subject to the shared Multi rollout
gate. Every enabled Server deployment includes the provider-neutral External Channel
Gateway.

Provider-native settings resolve either the parent channel's selected Agent, location,
and response-mode default or one exact connected thread Binding. Slack exposes signed
`/azents settings`, a `Conversation settings` message shortcut, and versioned presence
actions; Discord exposes signed application/message commands and presence actions.
Channel-to-Threads disconnects only the parent Binding. Threads-to-Channel creates no
empty Session; a later explicit eligible mention creates the new parent Binding.
Changing a Channel response mode updates the setting and connected parent Binding
atomically, while a Threads default change affects only future thread Bindings.

The Slack installation contract includes the `commands` scope, `/azents`, invocation
and conversation-settings message shortcuts, and enabled interactivity. HTTP manifests
use the fixed signed callback for Slash and interactivity Request URLs; Socket Mode
manifests omit those URLs. Existing customer-owned Apps receive a bounded configuration
update notice because Azents cannot change their manifest remotely.

Slack validation first uses `auth.test` to resolve the Team, Bot User ID, and Bot ID.
It retains `auth.test.user_id` as `provider_bot_user_id` and uses the separate Bot ID
only with `bots.info` to verify that the Bot Token's actual App ID equals the
configured App ID. An App ID copied from a different Slack App is rejected as a
recoverable configuration error rather than being marked active. Authenticated event
callbacks may also contribute a same-Team bot authorization identity for invocation
classification without another provider call. Validation checks the provider-reported
OAuth scope header when present and requires the message, conversation-history,
conversation-metadata, posting, and user identity scopes used by the adapter.
`files:read` and `files:write` independently grant download and upload capabilities;
either may remain unavailable without disabling text conversation.

Disconnect has no lifecycle-status admission guard. It disables inbound routing,
clears credentials, terminalizes owned live state, and commits the terminal
connection before attempting provider cleanup. Repeating disconnect is safe.
Disconnected rows remain as retained history roots but are omitted from the active
Agent connection list.

Session Channels shows bindings, the current Channel Work title, typed ordered
tasks, failed state, details, output, source links, Activity Tracker projection
state, grants, parent-channel versus thread location, concrete
response mode, and terminal disconnect state. Agent administrators may replace the
mode only while the binding remains connected and owned by the requested Agent and
Session. A parent Binding mutation updates its active participation setting in the
same transaction; a thread Binding mutation updates only itself. Disconnected historical
bindings retain their final mode as read-only state; foreign, missing, unauthorized,
and disconnected mutations use the not-found-shaped management boundary.
Approval and management detail surfaces show complete provider user identities with
copy controls, while regular timeline summaries remain name-first. Destructive
connection, binding, grant, and block actions require in-product confirmation.
Approval headers may wrap on narrow screens, and Session tabs remain horizontally
scrollable while hiding browser scrollbar chrome.

Approval links contain only an opaque access-request ID and require an authenticated
Agent administrator; unauthorized and missing requests are returned as not found.

Connection responses expose provider identity, capabilities, health, route relationship, and redacted credential state. They never return ciphertext or decrypted secret values.

## Scheduled Task Binding

A Scheduled Task may retain one exact connected Binding as an optional
presentation target. The Binding ID remains opaque and is revalidated against the
current Workspace, Agent, Session, resource, route, connection, and Agent
lifecycle before management or provider mutation. No parent/thread substitution
or fallback Binding is allowed.

Scheduled registration, progress, and terminal presentation reuse the common
provider-effect planning and execution primitives but own separate Scheduled
cycle projection state. They do not read or mutate Channel Work state. Signed
provider Edit/Delete controls bind the exact Task and Binding and revalidate the
current provider principal and interaction before mutation.

## Changelog

- **2026-08-20** (spec_version 63) — Added the connection-owned Discord Thread
  automatic archive duration, one-day migration/default, and non-secret Single/Multi
  policy updates that preserve active connection authority.
- **2026-08-16** (spec_version 62) — Added exact opaque Scheduled Task Binding
  authority, signed provider controls, and Scheduled-owned provider projection
  state distinct from Channel Work.

- **2026-08-14** (spec_version 61) — Corrected Discord Thread isolation to include
  independent participation: an unbound Thread requires its own explicit invocation,
  and parent `all_messages` authority applies only after the Thread owns a Binding.
- **2026-08-14** (spec_version 60) — Kept every existing Discord Thread as an
  independent conversation even when the parent participation location is `channel`;
  new Thread Bindings inherit the parent route and response mode, and `all_messages`
  may admit the first eligible ordinary Thread message.
- **2026-08-13** (spec_version 59) — Retained the bounded live-callback file count in
  content-free ingress items and treated a provider-history trigger snapshot with
  fewer files as a temporary failure so Slack and Discord attachment races reuse the
  existing queue retry policy.
- **2026-08-11** (spec_version 58) — Distinguished provider-native explicit
  invocation evidence from canonical prompt role: every active admitted item's exact
  human trigger correlates to `prompt_role=invocation`, including connected
  `all_messages` ordinary traffic, while unrelated retained history remains context.
- **2026-08-11** (spec_version 57) — Made `channel_action ignore` delete the
  requested binding's current Activity Tracker without a final reply while preserving
  `finish` reply-delivery gating and existing best-effort provider outcomes.
- **2026-08-11** (spec_version 56) — Reused one authenticated pinned `discord.py`
  Client session across caller-owned Discord REST workflows and isolated supported
  private HTTP calls behind signature-checked typed payload validation while retaining
  the existing direct-transport gaps and public Gateway lifecycle.
- **2026-08-10** (spec_version 55) — Clarified that every new Binding requires an
  explicit invocation and that `all_messages` authorizes only ordinary continuation on
  an existing connected Binding.
- **2026-08-10** (spec_version 54) — Generalized active ingress from
  Session-keyed drains to effective-conversation owners with source/target Resource
  separation, nullable Binding/Session readiness, Discord thread-before-Session
  preparation, bounded owner failure, and owner-scoped recovery.
- **2026-08-10** (spec_version 53) — Added active PostgreSQL ingress Session/item
  authority, first-one/later-ten draining, independent per-message mailbox rows,
  `prompt_role`, retry-tail/cursor-CAS recovery, one post-batch wake, and bounded
  diagnostics while removing synchronous callback processing and legacy batch-shaped
  mailbox authority.
- **2026-08-09** (spec_version 52) — Classified Discord current-Application
  Interaction Endpoint configuration as a narrow direct-transport gap until the
  adopted public SDK can transmit the endpoint field correctly.
- **2026-08-09** (spec_version 51) — Made silent Channel Work completion available
  for ordinary, initial, continuation, and mixed input through normal binding
  authority, without an unfinished-task veto.
- **2026-08-05** (spec_version 50) — Added Azents-owned typed Slack and Discord
  projection decoding at durable JSON boundaries while retaining request-local signed
  bodies and public SDK object ownership.
- **2026-08-04** (spec_version 49) — Removed `expected_size_bytes` and provider
  metadata-size gating from Slack and Discord downloads. The authenticated final URL
  `Content-Length` now exclusively declares transfer size and must match the streamed
  body exactly.
- **2026-08-04** (spec_version 48) — Added continuation-scoped binding authority for
  silent Channel Work completion that rejects unfinished tasks and produces no
  provider effect.
- **2026-08-04** (spec_version 47) — Distinguished required Runtime transfer services from provider connection capabilities and moved Runtime readiness resolution to Tool execution.
- **2026-08-03** (spec_version 46) — Moved binding-specific Channel Work and its
  ordered current provider projection parts into one Session-bound Toolkit State
  payload with independent whole-state optimistic concurrency and a stable work-cycle
  identity.
- **2026-08-03** (spec_version 45) — Preserved raw Slack and Discord user/channel
  references in model input and moved resolved names into a shared XML mapping appendix.
- **2026-08-03** (spec_version 44) — Added canonical `View session` navigation to
  every initial and updated Slack and Discord Activity Tracker without persisting
  URLs or changing Work projection ownership.
- **2026-08-03** (spec_version 43) — Applied saved lightweight-model title output modes and
  prompt-only invocation-markup guidance to External Channel creation without mutating canonical
  provider evidence or Discord projection ownership.
- **2026-08-03** (spec_version 42) — Added creation-bound one-shot automatic Session
  title eligibility and direct-created Discord provisional-title evidence, followed
  by one non-blocking post-title-commit GET and conditional PATCH with no recovery
  state.
- **2026-08-02** (spec_version 41) — Made normal Session Tool history the sole
  Agent-requested publication history, replaced non-Tool delivery work with
  process-local direct controls, and retained only owner-local current provider
  projection state.
- **2026-08-02** (spec_version 40) — Removed the deployment participation gate and
  made first-mention setup, participation settings, parent-channel Resources, and
  provider settings controls unconditional canonical behavior.
- **2026-08-02** (spec_version 39) — Added provider-channel participation settings,
  latest-source setup claims, explicit parent-channel Resources, setup continuation,
  provider-native settings controls, selected-Agent lifecycle coupling, and direct
  parent delivery without eager Binding or Session creation.
- **2026-08-01** (spec_version 38) — Added Agent defaults and concrete binding
  response modes, creation-time copy semantics, connected-only management, and
  `all_messages` compatibility for existing data.
- **2026-08-01** (spec_version 37) — Replaced the initial button-only Session
  navigation control with joined-presence copy and added leave-presence delivery to
  binding termination while retaining the canonical Session link.
- **2026-08-01** (spec_version 36) — Made the conversation position the sole
  duplicate-prevention authority and made Session-link and progress delivery
  independent from canonical mailbox acceptance, Session wake, and Agent execution.
- **2026-07-31** (spec_version 35) — Corrected Slack Bot User identity persistence
  to `auth.test.user_id` and recognized authenticated callback Bot User mentions when
  Slack delivers a human mention as a normal message event.
- **2026-07-31** (spec_version 34) — Added the dedicated External Channel
  continuation contract across runtime, persistence, model lowering, API, and UI.
- **2026-07-31** (spec_version 32) — Made `disconnected_at` the only binding
  connectedness authority, added canonical `/w` Session navigation, and removed
  transient ingress health from outbound REST authority.
- **2026-07-31** (spec_version 31) — Unified Slack Socket Mode and Discord Gateway
  ownership in one provider-neutral External Channel Gateway runtime and removed
  persistent transport ownership from general Agent Workers.
- **2026-07-31** (spec_version 30) — Replaced provider message/revision,
  conversation-admission, invocation-batch, provisioning, and wake-dispatch ownership
  with content-free interaction/access replay boundaries and one canonical mailbox
  item; changed file keys to carry direct provider coordinates.
- **2026-07-31** (spec_version 29) — Delegated Slack Socket endpoint acquisition,
  stale recovery, queue dispatch, and reconnect to the SDK; projected Slack and
  Discord typed lifecycle evidence through fenced health transitions; and made
  unexpected Slack Socket manager completion terminate Worker supervision.
- **2026-07-30** (spec_version 28) — Raised verified inbound attachment eligibility to
  500 MiB and retained provider bytes only in trusted verified staging. Caller-selected
  and provider metadata-size agreement from this version was removed by spec_version
  49.

- **2026-07-30** (spec_version 27) — Removed bot-trigger policy and inbound
  edit/delete correction behavior, made pending admission metadata-only and
  human-triggered, retained other visible author classes as history context, and
  documented safe Discord embed projection. Slack history identity enrichment resolves
  retained message senders even when their IDs do not appear in message bodies.
- **2026-07-30** (spec_version 26) — Replaced durable provider events,
  hydration/pending-context activation, and truncation projections with typed
  synchronous ingestion and provider-history content authority. The later
  `provider-260731` replacement removed the intermediate batch and wake owners.
- **2026-07-29** (spec_version 25) — Moved Discord's retained functional Channel Work
  Tracker into one bounded Embed without duplicating its body as ordinary message
  content.
- **2026-07-29** (spec_version 24) — Delegated Slack Socket Mode WebSocket transport
  mechanics to the public aiohttp SDK client while retaining Azents-owned lease,
  admission-before-acknowledgement, endpoint lifecycle policy, and reconnect decisions.
- **2026-07-28** (spec_version 23) — Aligned the provider boundary with high-level
  Slack Web API methods and SDK typed Socket envelopes while retaining Azents-owned
  Socket lifecycle, documented the single-message compact Discord Tracker, and made
  admitted-event processing resilient to transient iteration failures.
- **2026-07-28** (spec_version 22) — Promoted Runtime File Transfer as the current
  inbound/outbound file boundary: metadata-only durable state, authorized
  provider-to-Runtime staging, verified Runtime-to-provider publication, and no
  transfer-object authority outside trusted services.
- **2026-07-28** (spec_version 21) — Replaced custom Discord Gateway transport
  state with high-level typed `discord.py` callbacks, SDK-owned reconnect/Resume,
  provider-event idempotency, and lease-fenced canonical admission.
- **2026-07-28** (spec_version 20) — Added bounded Discord root/thread hydration,
  reconciliation-fenced activation, durable provisioned delivery-thread retention,
  and provider-correct Discord Multi management across public and Workspace surfaces.
- **2026-07-27** (spec_version 19) — Added route-scoped open human access and
  external-bot admission controls, with rejected authors excluded from releasable
  pending context and connected-bot loop prevention preserved.
- **2026-07-26** (spec_version 18) — Removed the Discord rollout gate, made the
  Gateway Worker part of every Server deployment, and specified provisional fenced
  callback authority so Discord's immediate PING verification can succeed without
  authorizing ordinary interactions.
- **2026-07-26** (spec_version 17) — Promoted Discord as a supported External
  Channel provider with customer-owned Single/Multi Apps, signed callback and
  Gateway authority, provider-safe attachment retrieval, rollout gating, and
  production-versus-deterministic-test endpoint boundaries.
- **2026-07-26** (spec_version 16) — Added immutable Single/Multi App modes,
  mode-aware route cardinality and resolution, durable selector/default state,
  Workspace Multi management, generation fences, and read-only disconnected history.
- **2026-07-24** (spec_version 15) — Defined provider-principal provenance as distinct from
  Userless Team Session execution and made External Channel wake-ups routing-only.
- **2026-07-24** (spec_version 14) — Added automatic Project policy snapshotting for
  new External Channel binding Sessions and immutable snapshot reuse for existing
  bindings.
- **2026-07-23** (spec_version 13) — Added metadata-only provider files, binding-scoped
  locators, independent file capabilities, Runtime transfer manifests, and the
  no-durable-file-body boundary.
- **2026-07-23** (spec_version 12) — Added provider-neutral titled Channel Work with rich typed tasks and failed state, Slack-native complete Plan rendering, typed management/UI projection, and visible-only Slack reference resolution.
- **2026-07-23** (spec_version 10) — Made approval-control delivery and access decisions converge in either completion order on one idempotent post-decision delete intent.
- **2026-07-23** (spec_version 9) — Separated raw Slack block normalization from trusted Azents admission projections so provider-supplied `normalized_text` cannot bypass supported-block traversal.
- **2026-07-23** (spec_version 8) — Separated one-time Session navigation from native task-card Activity Trackers, limited work cycles to 49 Todos, deleted Trackers after delivered final answers, and restricted replacement to active desired work.
- **2026-07-23** (spec_version 7) — Added work-cycle-owned Activity Tracker identity, pre-execution creation, retained delivered-answer completion, confirmed-deletion replacement, and current-work projection scoping.
- **2026-07-23** (spec_version 6) — Added bounded Block Kit fallback normalization, durable approval-control deletion, hard grant removal, delivery-derived Activity Tracker state, complete provider identities, in-product confirmations, and narrow-screen presentation behavior.
- **2026-07-23** (spec_version 5) — Added immutable bounded Slack reference mappings, readable external-message presentation, and connected-app self-message exclusion while retaining canonical provider IDs and bodies.
- **2026-07-23** (spec_version 4) — Removed route lifecycle state from persistence, routing, management responses, and UI. Connection health, Agent lifecycle, and binding/work/resource state now own their respective admission and termination decisions.
- **2026-07-22** (spec_version 3) — Separated provider health from Agent route lifecycle, fenced stale validation results, and required Slack conversation metadata scopes.
- **2026-07-22** (spec_version 2) — Added copy-ready Slack App setup guidance, App/Token ownership validation, complete connection replacement, unconditional idempotent disconnect, and active-list filtering for disconnected connections.
- **2026-07-22** (spec_version 1) — Promoted the External Channel ownership model, persistence graph, management API, security boundaries, Slack-first provider scope, and Session binding contract.
