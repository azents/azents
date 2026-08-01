---
title: "External Channel Authorization"
created: 2026-07-22
tags: [backend, frontend, external-channel, authorization, security, discord]
spec_type: flow
owner: "@Hardtack"
touches_domains: [external-channel, agent, conversation]
code_paths:
  - python/apps/azents/src/azents/services/external_channel/access.py
  - python/apps/azents/src/azents/services/external_channel/ingestion.py
  - python/apps/azents/src/azents/services/external_channel/ingestion_replay.py
  - python/apps/azents/src/azents/services/external_channel/mailbox_ingestion_store.py
  - python/apps/azents/src/azents/services/external_channel/mailbox_wake.py
  - python/apps/azents/src/azents/services/external_channel/transport_ingestion.py
  - python/apps/azents/src/azents/services/external_channel/interaction.py
  - python/apps/azents/src/azents/services/external_channel/selector.py
  - python/apps/azents/src/azents/services/external_channel/selector_state.py
  - python/apps/azents/src/azents/services/external_channel/shortcut_source.py
  - python/apps/azents/src/azents/services/external_channel/discord_events.py
  - python/apps/azents/src/azents/services/external_channel/discord_http.py
  - python/apps/azents/src/azents/services/external_channel/discord_interaction.py
  - python/apps/azents/src/azents/services/external_channel/management.py
  - python/apps/azents/src/azents/services/root_agent_session_creation/**
  - python/apps/azents/src/azents/repos/agent_automatic_project/**
  - python/apps/azents/src/azents/repos/external_channel/repository.py
  - python/apps/azents/src/azents/repos/external_channel/management.py
  - python/apps/azents/src/azents/api/public/external_channel/v1/management_route.py
  - python/apps/azents/src/azents/services/mailbox.py
  - python/apps/azents/src/azents/broker/types.py
  - python/apps/azents/src/azents/worker/session/execution_snapshot.py
  - typescript/apps/azents-web/src/app/(app)/external-channel/access/**
  - typescript/apps/azents-web/src/features/external-channel-approval/**
api_routes:
  - /external-channel/v1/approval-requests/{access_request_id}
  - /external-channel/v1/approval-requests/{access_request_id}/decision
  - /external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channel-access
last_verified_at: 2026-08-01
spec_version: 18
---

# External Channel Authorization

## Principal Boundary

An External Channel participant is an `ExternalChannelPrincipal`, not an Azents User
or WorkspaceUser. Provider identity is scoped by provider tenant and user ID. Human,
bot, app, and system authors are retained separately.

Every dedicated route has one automatic author-admission setting:

- `open_access_enabled` defaults to `true`. A human author may invoke the routed
  Agent without a per-principal grant unless an active block applies.

Only human authors are eligible triggers. Bot, app, and system callbacks never create
selector or approval state and do not consume the conversation read position. The
connected Azents provider bot is excluded from provider-history projection, preventing
output loops. Trigger eligibility is separate from contextual visibility: other
provider-visible humans, bots, and supported system messages remain in a later eligible
human invocation's bounded history. Blocks take precedence over grants and automatic
route access. A grant continues to authorize an eligible human when automatic route
access is disabled.

Only a human Multi App invocation can create selector state in its owning interaction.
Its catalog and route selection revalidate the initiating human principal before a
route-specific access decision. Duplicate source callbacks validate and reuse that
state; they never clear an already selected route.

The authenticated Azents administrator who grants or revokes access is a requester for that public
management operation only. Neither the administrator nor the ExternalChannelPrincipal becomes an
execution User. Once authorized work is durable, the linked Team Session is executed by the canonical
Session/Agent/Workspace/root-tree/Run snapshot after owner-generation claim. A broker wake contains
only `session_id`; it cannot carry or override provider, principal, requester, Agent, Workspace,
prompt, or resource authority.

## Restricted Human Flow

When `open_access_enabled` is disabled, an unknown human invocation cannot create an
AgentSession, binding invocation, or Agent wake-up until a grant is created. The
request retains an immutable provider-history replay boundary instead of a mutable
pending-context buffer. With the default open-human policy, an eligible unblocked
human follows synchronous authorized ingestion directly.

When a restricted participant invokes the Agent:

1. A bound thread or resolved Single/default route proceeds directly. An unresolved
   Multi App shortcut or mention first requires one explicit selector interaction and
   validates the chosen route. Slack presents its selector through Block Kit; Discord
   uses a verified command or component interaction.
2. Synchronous ingestion creates one idempotent access request for the selected route
   and metadata-only provider-history source identity.
3. The request snapshots the connection, conversation position, exclusive range start,
   and inclusive trigger position, expires after seven days, and contains an opaque ID.
4. One provider control-message intent is persisted and attempted once with the
   participant display label, complete provider user ID, and an authenticated Azents
   approval URL rendered through the provider's safe control shape. Pending selector
   and approval rows contain no provider body, revision, attachment metadata,
   reference mappings, or original-message URL.
5. The approval page requires an authenticated user who is an administrator of the routed Agent. Unauthorized, cross-Agent, missing, and expired requests do not disclose the request and appear not found or unavailable.

Selector completion does not grant access. It preserves the original sender and
uploader provenance, then applies the chosen Agent's existing grant, block, and
approval policy. The Slack or Discord callback actor can confirm interaction scope but
never becomes the execution User or replaces the initiating principal.

## Decisions

Supported decisions are `allow_session`, `allow_agent`, `deny`, and `block`.

- **Allow Session** creates or reuses the resource binding and grants the principal only for that AgentSession.
- **Allow Agent** creates or reuses the binding and grants the principal across connected bindings for that Agent.
- **Deny** resolves only the current request.
- **Block** resolves the request and creates an Agent-scoped block that takes precedence over grants.

The decision transaction first resolves the request identity, then locks and
revalidates the route connection, active resource and binding, and the same request.
It verifies an `active` or `degraded` ingress connection, available route,
active resource, and active Agent, creates the External Channel AgentSession only when
no connected binding exists, and writes the connected binding, grant, and decision
atomically. Repeating the same compatible Allow decision returns the existing binding
and grant. Conflicting or stale decisions return a conflict instead of creating
parallel state.

When Allow needs a new binding, the shared root Session creation boundary reads the
routed Agent's current automatic Project policy and creates the root
`SessionAgentContext` Project snapshot before the binding commit. It performs no
Runtime validation or filesystem access in this transaction; policy save-time
validation is authoritative. If the resource already has a connected binding, Allow
reuses that binding's Session and context snapshot instead of rereading or merging
the current policy. A newly created binding also copies the routed Agent's current
required External Channel response-mode default. Reusing a binding retains its
existing concrete mode.

When the original approval control message has a delivered provider identity, every
compatible final decision also creates one idempotent access-request-origin delete
intent in the decision transaction. The provider delete is attempted only after the
decision commits. Failed or ambiguous deletion remains a durable delivery outcome
and never rolls back the authorization result.

## Synchronous Replay and Context Release

Allow commits authorization before replay and then calls the shared synchronous
ingestion service with the request's immutable conversation-position boundary. The
service re-reads provider history outside a database transaction. If the shared
position is still before the trigger, it reads forward normally; if another accepted
invocation advanced past the trigger, it reuses the saved range start and exact trigger
boundary. It then reuses the committed binding and atomically commits the deterministic
canonical mailbox item, conversation-position advance, Session running transition, and
deterministic joined-presence and initial-progress delivery intents. Both position
cases converge on one mailbox item and logical wake.
Repeating a compatible Allow may perform the same provider-history replay to recover a
post-commit failure, but mailbox identity prevents another Session input or execution.
Replay failure never reverts the already committed access decision or binding, and it
does not couple provider-control delivery outcomes to accepted mailbox execution.
This durable replay remains available while connection ingress health is `active`,
`degraded`, or `reconnect_required`; `configuring`, `disconnecting`, and `disconnected`
connections cannot start it. Transient Gateway or Socket recovery therefore does not
revoke already committed replay and outbound REST authority.

The resulting mailbox item uses `wake_session` scheduling and contains the immutable
ordered provider-history projection rather than a raw callback or mutable
pending-context reference. At promotion, it becomes contiguous
`external_channel_message` events with
provider source attribution, trigger identity, authorization state, and one optional
leading omission reminder.

Later authorized original messages on a connected `all_messages` binding create
another canonical mailbox item and wake the same Session. A `mention_only` binding
requires an explicit invocation; ordinary messages remain provider-history context
without independent admission. Edit and delete callbacks are excluded in either mode;
they do not independently invoke the Agent or create a lifecycle/revision correction.

## Response-Mode Management Authorization

The Agent default and each connected binding mode use the existing External Channel
management authority. Reading the Agent-scoped default follows Agent visibility.
Replacing the default or a binding mode requires an explicit AgentAdmin relationship.
Binding mutation additionally scopes the row to the requested Workspace, Agent,
AgentSession, binding ID, and `disconnected_at IS NULL`. Unauthorized, cross-scope,
missing, and disconnected targets remain indistinguishable through the existing
not-found response. Neither mutation changes grants, blocks, route access policy,
principal identity, past messages, or already accepted work.

## Revocation

Agent administrators can revoke active grants or remove blocks. Grant revocation
locks and deletes the selected grant row, preventing future invocation without
deleting canonical messages, projected Session history, or unrelated grants.
Binding and connection disconnect remain separate lifecycle operations.

## Changelog

- **2026-08-01** (spec_version 18) — Added AgentAdmin-managed Agent and binding
  response modes, creation-time default copy in Allow, connected ownership scoping,
  and mention-only authorization-preserving admission.
- **2026-08-01** (spec_version 17) — Replaced the initial button-only Session link
  with a joined-presence control that retains canonical Session navigation.
- **2026-08-01** (spec_version 16) — Made Allow replay converge through the
  conversation position and canonical mailbox while provider-control delivery remains
  independent.
- **2026-07-31** (spec_version 14) — Replaced binding active/inactive state with
  terminal `disconnected_at` authority and retained durable Session-link and
  initial-progress delivery intents as independent provider controls.
- **2026-07-31** (spec_version 13) — Moved selector replay state into the owning
  interaction, kept approval replay in the access request, and made the canonical
  mailbox item the sole accepted-input and wake-recovery identity.
- **2026-07-30** (spec_version 12) — Removed bot-trigger admission and its route
  policy, made selector and approval state metadata-only, and excluded inbound
  edit/delete lifecycle corrections while retaining provider-visible nonhuman history
  as context for later human triggers.
- **2026-07-30** (spec_version 11) — Replaced pending-context and
  waiting-hydration release with immutable access-request replay boundaries and shared
  synchronous provider-history ingestion that converges before or after position
  advancement, and aligned Multi selector admission with route-level bot policy.
- **2026-07-28** (spec_version 10) — Verified that Discord selector and approval
  bindings use the shared hydration-fenced activation and source-provenance boundary.
- **2026-07-27** (spec_version 9) — Added route-scoped open human access by
  default, an opt-in external-bot admission setting, connected-bot loop exclusion,
  and the rule that rejected author classes never enter releasable pending context.
- **2026-07-26** (spec_version 8) — Extended the provider-neutral principal,
  source-retention, selector, and approval boundary to signed Discord interactions
  without allowing a callback actor to replace source provenance.
- **2026-07-26** (spec_version 7) — Inserted explicit Multi App selection before
  Agent-specific access evaluation while preserving source provenance, callback actor
  isolation, and duplicate selection/decision convergence.
- **2026-07-24** (spec_version 6) — Kept External Channel principal and administrator identity
  outside Team Session execution, which now derives only from canonical durable work after a
  routing-only wake.
- **2026-07-24** (spec_version 5) — Added atomic Agent automatic Project policy
  snapshotting for Allow-created binding Sessions and existing-binding snapshot
  reuse.
- **2026-07-23** (spec_version 4) — Added complete participant identity in approval controls, atomic post-decision control-message deletion intents, and hard removal of revoked grants.
- **2026-07-23** (spec_version 3) — Rendered Slack approval control messages as accessible Block Kit button actions.
- **2026-07-23** (spec_version 2) — Removed route lifecycle state from authorization admission; route identity remains while Agent lifecycle and resource state determine eligibility.
- **2026-07-22** (spec_version 1) — Promoted external-principal isolation, opaque approval, idempotent decisions, scoped grants/blocks, hydration-fenced activation, and same-binding pending-context release.
