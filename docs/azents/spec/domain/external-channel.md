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
last_verified_at: 2026-07-26
spec_version: 18
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
- Provider resources, canonical events, principals, messages, and immutable revisions are retained independently from AgentSession history.
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
| Connection | Workspace-owned provider App identity, immutable `single` or `multi` mode, encrypted credentials, capability/health snapshot, configuration and App-claim generations, terminal disconnect state, and provider ingress lease/checkpoint/gap state. Slack has one selected HTTP or Socket transport; Discord concurrently uses signed HTTP interactions and a Gateway session. |
| Agent route | Persistent connection-to-Agent relationship. Single Apps require exactly one current route. Multi Apps retain zero or more available or removed catalog routes; immutable Agent identity snapshots preserve history after Agent deletion. |
| Channel default | Multi App channel-to-route preference. At most one active default exists per connection and provider channel. Removing its route invalidates rather than silently retargets it. |
| Conversation admission | Durable, expiring unbound-conversation scope that records the initiating provider principal and may become selected exactly once. |
| Interaction | Idempotent signed Slack or Discord shortcut, component/action, navigation, or submission claim. Provider triggers and Discord interaction tokens stay transient and are never persisted or replayed. |
| Resource | One provider conversation: a Slack thread or Discord thread, with provider labels, availability, hydration cursor/high-watermark, reconciliation boundary, and latest activity. |
| Event | Durable provider envelope admission keyed by connection and provider event identity. Processing is at-least-once and domain writes are idempotent. |
| Principal | Provider tenant/user identity and author category. It is not an Azents User or WorkspaceUser. |
| Message and revision | Canonical provider message plus immutable original/edit/delete revisions. Slack messages prefer non-blank fallback text and otherwise derive bounded readable text from supported Block Kit content. Discord Gateway messages are normalized only after target-Guild, author, content, and message eligibility checks. Raw provider payloads cannot supply Azents' internal normalized-text projection; only the authenticated admission projection may be consumed through the trusted projection path. Revisions retain optional bounded provider identity mappings and up to 20 metadata-only file entries. Supported entries expose binding-scoped opaque locators; private URLs and file bodies are never persisted or rendered. |
| Pending context | Unprojected same-route/resource revisions retained for at most 7 days, 100 messages, and 256 KiB. Oldest content is expired or trimmed first. |
| Binding | Active or disconnected link from one route/resource to one AgentSession. Initial activation waits for hydration reconciliation. |
| Invocation batch | Immutable ordered revision membership released through one authorized trigger and referenced by a batch InputBuffer. |
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
- An unbound resource resolves only through an existing binding, the Single App's
  sole route, a valid Multi App channel default, or explicit selector completion, in
  that order. It never chooses an arbitrary candidate. A resource has at most one
  active binding, so a later Agent choice cannot replace an established thread.
- Durable execution mutations are fenced by the current Session owner generation.
  Provider principals, Slack callback actors, Workspace requesters, and approvers
  remain provenance or authorization identities and never become the execution User.
- A resource is `active`, `unavailable`, or `deleted`; hydration is `pending`, `running`, `complete`, `bounded`, or `incomplete`.
- A binding is either active or disconnected. Activation moves from `waiting_hydration` to `active` only after the admitted-event reconciliation boundary is clear.
- Connection capabilities expose `download_files` and `upload_files` independently.
  Missing legacy fields are unavailable. A file locator is valid only for the current
  Agent, Session, active binding, route, and active or degraded connection; provider
  authorization remains authoritative at download time.
- A Discord connection is scoped to its validated Application and target Guild. The
  callback selector is opaque and retained only as a hash; the Application public key,
  Bot identity, and callback authority are configuration-derived state. Discord
  interaction tokens, callback URLs, raw interaction bodies, and signature values are
  never durable External Channel state.
- The dedicated Discord Gateway Worker claims each connection through owner,
  configuration-generation, App-claim-generation, and lease-generation fences.
  Heartbeats and lease renewal do not authorize durable mutation by themselves. A
  Gateway dispatch advances the encrypted Resume checkpoint only in the same durable
  admission transaction that accepts the canonical event; an unadmitted dispatch is
  not checkpointed. Gateway `READY` is session state, not a canonical message event.
- Production Discord REST and Gateway endpoints require `https` and `wss`. The
  deterministic test origin may use `http` and `ws` only when an explicit test REST
  origin and an explicit insecure-Gateway opt-in are both configured.
- Supported first-release inbound files are direct Slack-hosted uploads with a concrete
  ID, non-negative declared size, visible access, and no external or Slack Connect
  classification. Unsupported entries remain metadata-visible with a stable rejection
  reason but cannot be materialized.
- Discord attachment metadata likewise stores bounded identifiers, filename, media type,
  and declared size only. A current provider message lookup obtains a non-durable
  download URL immediately before a bounded in-memory download; redirects, stale
  authority, malformed metadata, and oversized streams fail closed.
- Initial binding activation creates one separate button-only Session navigation
  message. Releasing a new invocation batch creates the current work cycle's
  Activity Tracker before Session wake-up. Checking and task progress update one
  retained provider message; a delivered final answer deletes it, and separate work
  cycles never share that identity.
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
- Message revisions never rewrite an already projected revision. Later edits or deletes remain distinct corrections.
- A Session- or Agent-scoped grant authorizes invocation only for the same Agent, principal, route relationship, and active resource. Blocks take precedence.
- Creating a new binding Session snapshots the routed Agent's current automatic
  Project policy into the root `SessionAgentContext` in the same transaction as
  Session and binding creation. This applies both to an administrator Allow
  decision and to initial binding creation for an already Agent-authorized
  principal. Reusing an existing binding keeps its existing Session/context
  Project snapshot; later policy changes are not retroactive.
- Restore never reactivates a disconnected binding, ended work item, removed pending context, or connection.

## Management Surface

Agent administrators manage Single Apps from Agent settings. They can retrieve a
complete copy-ready Slack App Manifest, follow equivalent manual Slack UI
instructions, create the App and its sole route, validate it, replace its App ID,
transport, and complete credential set, disconnect it terminally, and manage grants
and blocks. Removing the Single association disconnects the App. Secret fields
remain blank and required when an existing connection is edited.

Workspace Owners and Managers manage Multi Apps from Workspace integrations.
Ordinary Members have neither Multi read nor write authority. Multi creation starts
with zero Agents and remains rollout-gated. The management surface supports paged App
and Agent catalogs, idempotent Agent association, removed-route re-enable, channel
defaults, validation and complete credential replacement, impact previews, and
generation-fenced route removal/default mutation/App disconnect. Disconnected Multi
Apps remain readable historical records but accept no further mutation.

Agent settings show associated Multi Apps as Workspace-managed read-only context.
Slack can open an opaque, expiring management handoff for the current Multi App
channel; the authenticated Web surface rechecks Workspace write permission and
handoff scope before reading or replacing that channel's default.

Discord Single and Multi setup use separate Agent and Workspace flows. A connection
validates that its Bot Token belongs to the submitted Discord Application, retains the
target Guild identity, durably prepares the opaque callback selector hash and
Application public key behind the current credential and configuration-generation
fences, then configures the signed-interaction callback. This preparation accepts only
Discord PING verification; ordinary interactions remain unauthorized until the
activation commit. A failed provider registration clears the provisional callback
authority behind the same fences and requires reconnection. Replacing Discord
credentials or App identity invalidates prior callback and Gateway authority before
activation repeats. Discord is available without a deployment-scoped provider rollout
flag; every enabled Server deployment includes the dedicated Gateway Worker.

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
state, truncation, delivery outcomes, grants, and terminal disconnect state.
Approval and management detail surfaces show complete provider user identities with
copy controls, while regular timeline summaries remain name-first. Destructive
connection, binding, grant, and block actions require in-product confirmation.
Approval headers may wrap on narrow screens, and Session tabs remain horizontally
scrollable while hiding browser scrollbar chrome.

Approval links contain only an opaque access-request ID and require an authenticated
Agent administrator; unauthorized and missing requests are returned as not found.

Connection responses expose provider identity, capabilities, health, route relationship, and redacted credential state. They never return ciphertext or decrypted secret values.

## Changelog

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
