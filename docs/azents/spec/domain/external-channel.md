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
  - python/apps/azents/src/azents/core/external_channel_progress.py
  - python/apps/azents/src/azents/core/slack_external_channel_progress.py
  - python/apps/azents/src/azents/core/enums.py
  - python/apps/azents/src/azents/engine/events/external_channel_rendering.py
  - python/apps/azents/src/azents/rdb/models/external_channel.py
  - python/apps/azents/src/azents/repos/external_channel/**
  - python/apps/azents/src/azents/services/external_channel/**
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
  - /external-channel/v1/approval-requests/{access_request_id}
last_verified_at: 2026-07-30
spec_version: 28
---

# External Channel

## Overview

External Channels connect provider conversations to Azents Agents without treating provider credentials, conversations, participants, or delivery state as AgentSession-owned chat data. Workspace owns connection credentials and provider identity. An Agent route selects the Agent for a connection. A resource represents one provider conversation, and an active binding links that resource to one AgentSession.

Slack and Discord are supported providers. A Slack connection uses a manually
configured Slack App and selects either signed HTTP callbacks or Socket Mode. A Discord
connection uses a customer-owned Discord App, its Bot Token, one target Guild, a signed
interaction callback, and a dedicated Gateway Worker. Both providers have an immutable
App mode. A Single App is managed by one Agent's administrators and has exactly one
Agent route. A Multi App is managed by Workspace Owners and Managers and may have zero
or more Agent routes. One Agent may appear in several Apps, and one AgentSession may
contain multiple independent bindings.

## Ownership and Security Boundaries

- Connection and route records are Workspace/Agent administration state.
- Provider resources, principals, messages, and immutable revisions are retained independently from AgentSession history.
- Bindings, invocation batches, Channel Work, channel actions, and delivery attempts are Session lifecycle resources.
- Credentials are encrypted at rest and decrypted only inside provider adapters. Public APIs, generated clients, prompts, events, logs, UI state, and test evidence expose only redacted credential status.
- Provider message content remains external input even after approval. It retains provider, resource, sender, author type, authorization, message identity, and revision attribution.
- An ExternalChannelPrincipal is provider provenance and admission authority only. It is never an
  Azents execution User. After a binding releases durable work, the linked Team Session executes
  through canonical Session/Run authority without inferring a User from the principal, approver,
  route owner, Agent creator, Workspace owner, or broker signal.
- External Channel wake-ups are routing-only `SessionWakeUp(session_id)` notifications. The batch,
  binding, provider principal, and source content are loaded from durable records after the Worker
  claims owner generation; they are not carried by the broker.
- Foreign keys are restrictive across lifecycle roots. AgentSession deletion cannot cascade away provider or audit roots before lifecycle cleanup and verification complete.

## Core Records

| Record | Current contract |
| --- | --- |
| Connection | Workspace-owned provider App identity, immutable `single` or `multi` mode, encrypted credentials, capability/health snapshot, configuration and App-claim generations, terminal disconnect state, and provider ingress lease/gap state. Slack has one selected HTTP or Socket transport; Discord concurrently uses signed HTTP interactions and a Gateway session. |
| Agent route | Persistent connection-to-Agent relationship. Single Apps require exactly one current route. Multi Apps retain zero or more available or removed catalog routes; immutable Agent identity snapshots preserve history after Agent deletion. Each active dedicated route defaults to open human access and separately defaults to rejecting external bot messages. |
| Channel default | Multi App channel-to-route preference. At most one active default exists per connection and provider channel. Removing its route invalidates rather than silently retargets it. |
| Conversation admission | Durable, expiring unbound-conversation scope that records the initiating provider principal and may become selected exactly once. |
| Interaction | Idempotent signed Slack or Discord shortcut, component/action, navigation, or submission claim. Provider triggers and Discord interaction tokens stay transient and are never persisted or replayed. |
| Resource | One provider conversation: a Slack thread or Discord root/thread, with provider labels, availability, latest activity, and any provisioned delivery-thread identity. Discord labels separately retain source channel, parent channel, root message, existing thread, and provisioned delivery thread identities. |
| Conversation position | Durable read-through position for one connection-scoped parent channel or thread. PostgreSQL position compare-and-set is the ordering authority across retries and replicas. |
| Principal | Provider tenant/user identity and author category. It is not an Azents User or WorkspaceUser. |
| Message and revision | Canonical provider-history snapshot plus immutable accepted revisions. Slack messages prefer non-blank fallback text and otherwise derive bounded readable text from supported Block Kit content. Slack identity mappings include each retained message sender as well as bounded body references. Discord messages are normalized only after target-Guild, author, content, and message eligibility checks. Raw callback payloads are never canonical content authority. Revisions retain optional bounded provider identity mappings and up to 20 metadata-only file entries. Supported entries expose binding-scoped opaque locators; private URLs and file bodies are never persisted or rendered. |
| Binding | Active or disconnected link from one route/resource to one AgentSession. A new authorized conversation creates an active binding in the final synchronous acceptance transaction. |
| Invocation batch | Immutable ordered revision membership released through one authorized trigger, linked to its conversation position and mailbox item, and carrying recoverable wake-dispatch state. |
| Access request/grant/block | Opaque approval request, Session- or Agent-scoped grant, and Agent-scoped block for one external principal. Final decisions retain their authorization result independently from post-commit approval-control cleanup. |
| Channel Work/action/delivery | Binding-scoped durable current-work title and ordered provider-neutral tasks with stable identities, status, optional details, optional output, and labeled URL sources; one work-cycle-owned desired progress state and provider identity; one atomic explicit action; and persisted provider intents/outcomes. File-bearing replies retain only bounded Runtime source manifests and delivery phase evidence. Management derives projection state from the latest progress operation belonging to the current work cycle. |

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
- Slack Socket Mode mints endpoints through the same high-level SDK client. The public
  aiohttp `SocketModeClient` owns WebSocket connection mechanics, Ping/Pong, frame
  receipt, and acknowledgement transmission with SDK automatic reconnect disabled.
  Azents owns the fenced lease, endpoint-scoped connect/close policy, durable admission,
  acknowledgement ordering, normalized reconnect decision, and gap persistence. Public
  SDK Socket Mode request and response types validate envelopes and construct
  acknowledgements.
- An unbound resource resolves only through an existing binding, the Single App's
  sole route, a valid Multi App channel default, or explicit selector completion, in
  that order. It never chooses an arbitrary candidate. A resource has at most one
  active binding, so a later Agent choice cannot replace an established thread.
- Durable execution mutations are fenced by the current Session owner generation.
  Provider principals, Slack callback actors, Workspace requesters, and approvers
  remain provenance or authorization identities and never become the execution User.
- A resource is `active`, `unavailable`, or `deleted`. Provider history is read on demand for one synchronous ingestion operation and has no durable hydration lifecycle.
- A binding is either active or disconnected. There is no waiting-hydration activation state.
- Connection capabilities expose `download_files` and `upload_files` independently.
  Missing legacy fields are unavailable. A file locator is valid only for the current
  Agent, Session, active binding, route, and active or degraded connection; provider
  authorization remains authoritative at download time.
- File-bearing External Channel state retains provider metadata, opaque locators,
  bounded Runtime transfer manifests, consumer-claim identity, and terminal delivery
  evidence only. Provider bodies enter the common Server-to-Runtime transfer path only
  after a current authorization recheck. Runtime bodies leave through one verified
  Runtime-to-provider transfer per source. No External Channel row, event, prompt,
  queue payload, or delivery record stores transfer bytes, provider upload URLs,
  object-store credentials, object keys, or trusted object handles.
- A Discord connection is scoped to its validated Application and target Guild. The
  callback selector is opaque and retained only as a hash; the Application public key,
  Bot identity, and required Guild Message Command identifier are
  configuration-derived state. Discord
  interaction tokens, callback URLs, raw interaction bodies, and signature values are
  never durable External Channel state.
- The dedicated Discord Gateway Worker claims each connection through owner,
  configuration-generation, App-claim-generation, and lease-generation fences.
  Heartbeats and lease renewal do not authorize durable mutation by themselves.
  The Worker uses only public high-level `discord.py` APIs and typed SDK callbacks.
  The SDK owns discovery, heartbeat, reconnect, and in-process Resume. Azents neither
  reads raw Gateway payloads/private SDK state nor persists a cross-process Gateway
  Resume checkpoint. Durable provider-event idempotency and the current
  lease/configuration/App-claim fence protect canonical admission.
- Production Discord Gateway endpoint selection belongs to `discord.py`; Azents does
  not expose a custom or insecure Gateway endpoint override.
- Inbound Slack and Discord attachments retain only bounded identifiers, filename, media
  type, and an exact non-negative declared byte size in durable state. An attachment is
  materialized only after the Agent supplies that displayed size to
  `download_external_file`; absent or unsupported metadata remains visible but is not
  downloadable.
- The trusted provider adapter refreshes current metadata, requires one matching HTTP
  `Content-Length`, streams and counts the response body, and stages an immutable
  verified object before Runtime delivery. Any metadata, response-header, or body-size
  mismatch fails closed without a Runtime destination commit; provider URLs and bytes
  remain outside durable External Channel state.
- Initial synchronous binding acceptance creates one separate Session navigation message
  and one checking work projection before Session wake-up. Slack lowers work through its
  retained Tracker message; Discord lowers each work snapshot to one retained compact
  Embed Tracker. The Embed title carries the current-work title, while its bounded
  description carries the status summary, every ordered task title and status marker,
  then prioritized details, output, and labeled sources. The functional Tracker body is
  not duplicated as ordinary message content; Multi App Agent attribution remains
  separate readable content. A
  Discord root source provisions or reuses one delivery thread after route resolution,
  persists that target, and sends approval controls, Session navigation, replies,
  files, progress, recovery, and cleanup to that thread. A delivered final answer
  deletes active progress, and separate work cycles never share provider identities.
- The Tracker uses one native read-only Slack task card before Channel Work is
  declared. Once tasks exist, one native Slack plan carries the Agent-authored
  current-work title and up to 49 ordered tasks. Canonical task states are
  `pending`, `in_progress`, `completed`, and `failed`; Slack lowers them to
  `pending`, `in_progress`, `complete`, and `error`. Nested Plan tasks omit a
  standalone block `type` and may contain literal rich-text details/output and
  labeled HTTP or HTTPS sources. The payload sends no Slack `plan_id`.
- Channel Work desired state is a versioned provider-neutral complete snapshot.
  A serialized desired snapshot is limited to 64 KiB and is rejected atomically
  before canonical state changes when it exceeds that bound.
  Slack-specific blocks and revision-derived `block_id` values are created only
  at the provider presentation boundary. Slack streaming is not used; retained
  `chat.postMessage` and `chat.update` mutations apply complete snapshots.
- Confirmed deletion clears only the matching Tracker identity and creates one
  replacement from durable desired state while work remains active. A replacement
  that captured an older desired revision is updated once to the latest state after
  creation. Finished work never recreates a Tracker, and a missing delete target is
  already absent.
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
  Session and binding creation. This applies both to an administrator Allow
  decision and to initial binding creation for an already Agent-authorized
  principal. Reusing an existing binding keeps its existing Session/context
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

Workspace Owners and Managers manage provider-scoped Multi Apps from Workspace
integrations. Ordinary Members have neither Multi read nor write authority. Slack and
Discord Multi creation start with zero Agents. Their provider-correct public API,
generated clients, tRPC, and Workspace UI support paged connection and route catalogs,
idempotent Agent association, removed-route re-enable, channel defaults, validation
and complete credential replacement, impact previews, and generation-fenced route
removal/default mutation/App disconnect. Disconnected Multi Apps remain readable
historical records but accept no further mutation.

Agent settings show associated Multi Apps as Workspace-managed read-only context.
Slack can open an opaque, expiring management handoff for the current Multi App
channel; the authenticated Web surface rechecks Workspace write permission and
handoff scope before reading or replacing that channel's default.

Discord Single and Multi setup use separate Agent and Workspace flows. A connection
validates that its Bot Token belongs to the submitted Discord Application, retains the
target Guild identity, durably prepares the opaque callback selector hash and
Application public key behind the current credential and configuration-generation
fences, then configures the signed-interaction callback and reconciles the required
Guild-scoped `Ask an Azents Agent` Message Command. This preparation accepts only
Discord PING verification; ordinary interactions remain unauthorized until the
activation commit. A failed provider registration clears the provisional callback
authority behind the same fences and requires reconnection. Replacing Discord
credentials or App identity invalidates prior callback and Gateway authority before
activation repeats. Dedicated Discord setup is available without a deployment-scoped
provider rollout flag; Discord Multi App creation is subject to the shared Multi rollout
gate. Every enabled Server deployment includes the dedicated Gateway Worker.

Slack validation first uses `auth.test` to resolve Team and Bot identity, then uses
`bots.info` to verify that the Bot Token's actual App ID equals the configured App
ID. An App ID copied from a different Slack App is rejected as a recoverable
configuration error rather than being marked active. Validation also checks the
provider-reported OAuth scope header when present and requires the message,
conversation-history, conversation-metadata, posting, and user identity scopes used
by the adapter. `files:read` and `files:write` independently grant download and upload
capabilities; either may remain unavailable without disabling text conversation.

Disconnect has no lifecycle-status admission guard. It disables inbound routing,
clears credentials, terminalizes owned live state, and commits the terminal
connection before attempting provider cleanup. Repeating disconnect is safe.
Disconnected rows remain as retained history roots but are omitted from the active
Agent connection list.

Session Channels shows bindings, the current Channel Work title, typed ordered
tasks, failed state, details, output, source links, Activity Tracker projection
state, delivery outcomes, grants, and terminal disconnect state.
Approval and management detail surfaces show complete provider user identities with
copy controls, while regular timeline summaries remain name-first. Destructive
connection, binding, grant, and block actions require in-product confirmation.
Approval headers may wrap on narrow screens, and Session tabs remain horizontally
scrollable while hiding browser scrollbar chrome.

Approval links contain only an opaque access-request ID and require an authenticated
Agent administrator; unauthorized and missing requests are returned as not found.

Connection responses expose provider identity, capabilities, health, route relationship, and redacted credential state. They never return ciphertext or decrypted secret values.

## Changelog

- **2026-07-30** (spec_version 28) — Raised verified inbound attachment eligibility to
  500 MiB, bound Agent selection to the displayed byte size, required matching current
  metadata/HTTP `Content-Length`/received-body evidence, and retained provider bytes
  only in trusted verified staging.

- **2026-07-30** (spec_version 27) — Removed bot-trigger policy and inbound
  edit/delete correction behavior, made pending admission metadata-only and
  human-triggered, retained other visible author classes as history context, and
  documented safe Discord embed projection. Slack history identity enrichment resolves
  retained message senders even when their IDs do not appear in message bodies.
- **2026-07-30** (spec_version 26) — Replaced durable provider events,
  hydration/pending-context activation, and truncation projections with typed
  synchronous ingestion, parent/thread conversation positions, immutable invocation
  batches, active binding acceptance, recoverable wake state, and provider-history
  content authority.
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
