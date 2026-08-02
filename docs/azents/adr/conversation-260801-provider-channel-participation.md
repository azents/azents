---
title: "Provider Channel Participation Settings"
created: 2026-08-01
tags: [architecture, external-channel, slack, discord, conversation]
document_role: primary
document_type: adr
snapshot_id: conversation-260801
---

# conversation-260801/ADR: Provider Channel Participation Settings

## Context

The confirmed
[conversation-260801/REQ](../requirements/conversation-260801-provider-channel-participation.md)
requires an explicit conversation-location choice for each provider connection,
parent channel, and selected Agent relationship. An unconfigured first mention must
not create a runnable Session input, AgentRun, or connected conversation Binding. Once
an authorized provider participant selects `Channel` or `Threads`, the original
mention continues with its original source provenance, and later provider-native
settings actions may change the shared location and response mode.

The current system already distinguishes parent-channel and thread conversation
positions, and PostgreSQL position compare-and-set plus canonical mailbox identity
own ordering, duplicate prevention, and wake recovery. External Channel Resources and
Bindings, however, currently represent only isolated thread conversations. A first
authorized invocation creates the thread Resource, concrete Binding, root Session,
canonical mailbox input, running transition, and independent provider-control intents
without a conversation-location gate.

A Binding has one required concrete `mention_only` or `all_messages` mode. Binding
creation copies the Agent's current External Channel default; existing Bindings do not
dynamically inherit later changes. Terminal Binding disconnect preserves the linked
Session and history and never reactivates that Binding.

The current Multi App channel default is only a route preference. It is keyed by a
connection and provider channel and selects one Agent route when invocation is
otherwise ambiguous. It cannot serve as the Agent-channel participation setting,
because multiple Agents in the same Multi App channel must have independent
conversation settings and route preference must not silently overwrite them.

Existing selector, access-request, and provider-interaction paths provide content-free
source locators, provider principal provenance, signed callback scope, immutable
conversation-position replay boundaries, and idempotent callback claims. Slack does
not currently admit Slash Commands, and neither provider currently exposes
conversation settings through joined-presence controls or message-context actions.
These are implementation gaps rather than alternative current authorities.

The Requirements already fix the product behavior for Agent-channel identity,
participant authorization, Channel and Threads routing, response-mode inheritance,
location transitions, provider-native capability adaptation, original-author
provenance, Session-history preservation, and separation of provider-control delivery
from canonical mailbox, wake, and AgentRun authority. Those decisions are not reopened
here.

## Context Amendment

Before the Design was created, the requester amended and reconfirmed
`conversation-260801/REQ-5`: a Multi App may contain many Agent routes, but one
provider parent channel has only one selected default Agent. Different Agents may
still own isolated thread Bindings in that channel through explicit selection, but
parent-channel participation never fans out across several Agents. Decision
`conversation-260801/ADR-D10` supersedes the earlier per-route parent-setting identity
assumption while preserving the separate route-default and conversation-setting
responsibilities.

## Decision Backlog

Discussion proceeds in dependency order. A backlog item becomes an accepted
`conversation-260801/ADR-DN` decision only after requester approval.

1. **Accepted, then superseded by the one-Agent channel contract** — the setting
   retains its route reference but its active identity is provider-channel scoped.
2. **Accepted: Channel conversation identity** — a parent channel is a first-class
   External Channel Resource using the normal Binding and Session lifecycle.
3. **Accepted, superseding the initial first-owner rule: concurrent unconfigured
   mentions** — one shared setup claim exists, and the latest eligible mention owns
   continuation while the choice remains pending.
4. **Accepted: setup claim and replay authority** — dedicated setup state owns the
   current pre-Session source boundary and provider interactions remain callback claims.
5. **Accepted: response-mode authority across locations** — the Agent-channel setting
   owns the default for new Bindings, while each Binding remains the concrete
   execution authority.
6. **Accepted: compatibility migration** — existing thread Bindings remain unchanged
   and do not backfill or imply Agent-channel settings.
7. **Accepted: route and Agent lifecycle** — route removal, Agent deletion, and
   terminal connection disconnect invalidate settings without later restoration.
8. **Accepted: setup-control discoverability and recovery** — later mentions,
   commands, context actions, stale controls, and bounded delivery recovery
   re-surface one pending setup claim without creating another continuation owner.
9. **Accepted: Multi App parent-channel dispatch cardinality** — one provider channel
   has one selected Agent and one active parent-channel setting; ordinary messages
   never fan out across Agent routes.

Stable lock ordering, setting-generation fencing, final admission revalidation,
provider-specific command and action identifiers, modal layout, migration mechanics,
OpenAPI client generation, and deterministic provider-fake construction remain
reversible Design details rather than requester decisions.

## Decisions

### conversation-260801/ADR-D1 — Agent-channel settings belong to the persistent route relationship

One durable Agent-channel participation setting belongs to a provider connection,
provider parent channel, and persistent Agent route relationship. Its canonical
identity is therefore `(connection_id, provider_parent_channel_id, route_id)`.

The setting is a separate lifecycle root from the Multi App channel default. It owns
the current conversation location, parent response-mode default, mutation generation,
provider-principal configuration provenance, and invalidation state. The route
continues to own the stable connection-to-Agent relationship and retained Agent
identity snapshot. The same setting model applies to Single and Multi Apps.

This decision applies to `conversation-260801/REQ-1`, `REQ-5`, `REQ-9`, `REQ-11`,
`REQ-13`, and `REQ-15`.

Keying the setting directly by the current Agent foreign key is rejected because
Agent deletion would conflict with historical identity retention. Keying it only by
an unconstrained Agent identity snapshot is rejected because every read and mutation
would have to rediscover and separately validate the current route lifecycle. Reusing
the Multi App channel default is excluded by the Requirements because that record
selects one route for ambiguous invocation and cannot represent independent settings
for multiple Agents in the same provider channel.

### conversation-260801/ADR-D2 — Parent channels are first-class conversation Resources

`parent_channel` is added as a first-class External Channel Resource type. A Channel
location uses one connected Binding from that Resource to one root AgentSession and
therefore reuses the existing concrete response mode, Channel Work, Session
navigation, provider delivery, disconnect, cleanup, and retained-history lifecycle.

A parent-channel Resource and any number of provider thread Resources may coexist for
the same connection and provider channel. Top-level Channel traffic resolves only the
parent-channel Resource. Provider thread traffic continues to resolve an isolated
thread Resource and is never merged into the parent-channel Session.

Changing from Channel to Threads terminally disconnects only the connected
parent-channel Binding. The Resource and Session history remain. A later Channel
activation may reuse the provider Resource identity but must create a new Binding and
new Session rather than reactivating the disconnected Binding.

This decision applies to `conversation-260801/REQ-4`, `REQ-6`, `REQ-7`, `REQ-10`,
`REQ-13`, and `REQ-15`.

A separate channel-conversation relationship is rejected because it would duplicate
Binding lifecycle, response-mode, work, delivery, management, and cleanup authority.
Representing a parent channel as a synthetic thread Resource is rejected because it
would preserve the current incorrect thread-only semantic and require provider target
conditionals throughout history, delivery, and lifecycle handling.

### conversation-260801/ADR-D3 — One first mention owns shared setup continuation

The first eligible mention that atomically acquires the unconfigured Agent-channel
setup claim becomes the only original trigger eligible for automatic continuation.
The setup prompt is shared for that Agent-channel relationship, and any currently
authorized provider human may complete it without replacing the owning trigger's
author, message identity, source position, or execution provenance.

Additional eligible mentions received while the same setup claim remains pending do
not create another setup claim, replay boundary, Session, Binding, mailbox input, or
AgentRun. They are not automatically executed after setup. New mentions received
after the setting commits follow the selected location and response-mode behavior
normally.

This single-continuation rule does not limit setup discoverability to one provider
message. A later explicit mention may re-surface a fresh provider control referencing
the same pending setup claim without becoming another continuation owner. A trusted
Slash Command or message-context action may reopen the same pending setup. Every
stale or newly rendered control revalidates the same claim and, after completion,
converges on the committed current setting rather than replaying another mention.

This decision applies to `conversation-260801/REQ-2`, `REQ-3`, and `REQ-4`.

Retaining and releasing every concurrent mention is rejected because selecting
Threads could fan one shared configuration action into multiple new Sessions and
AgentRuns. Replacing the setup owner with the latest mention is rejected because the
visible prompt and continuation provenance would become race-dependent and the first
eligible request could be silently displaced.

### conversation-260801/ADR-D4 — Dedicated setup claims own pre-Session continuation

One dedicated Agent-channel setup claim owns the shared pending setup lifecycle and
the first mention's immutable, content-free continuation boundary. Its identity is
scoped by the connection, provider parent channel, and route selected in
`conversation-260801/ADR-D1`. At most one pending claim exists for that relationship.

The setup claim retains only the provider source locator, original principal,
conversation-position identity, exclusive range start, inclusive trigger position,
and bounded coordination state required to continue the original mention. It creates
or owns no Session, Binding, mailbox input, or AgentRun.

Signed Slack and Discord interactions remain individual, expiring callback claims.
They reference and revalidate the setup claim but do not own its continuation
authority. Multiple controls and callback claims may reference the same pending setup
so the choice remains discoverable after provider messages scroll away or interaction
tokens expire. A successful choice creates the canonical Agent-channel setting; an
unselected, expired, or failed setup claim never becomes a setting with a null or
pseudo location.

This decision applies to `conversation-260801/REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, and
`REQ-14`.

Storing all setup state in a generic interaction projection is rejected because
provider callbacks and controls may expire or be replaced independently from the
shared original-trigger continuation. Creating the canonical setting before a
location is chosen is rejected because it would combine durable configuration with
ephemeral replay state and introduce a persisted pseudo-configuration.

### conversation-260801/ADR-D5 — The latest eligible mention owns pending continuation

While one Agent-channel setup claim remains pending, each later eligible explicit
mention atomically replaces that claim's continuation source, principal, provider
message identity, and inclusive trigger boundary. The claim remains the only setup
and continuation owner; replacement creates no additional claim, Session, Binding,
mailbox input, or AgentRun.

When a participant completes setup, the selection transaction locks and revalidates
the claim and continues the latest source committed before that selection. The
selected mention retains its own author and message provenance. Earlier provider
messages may remain visible as bounded provider-history context but are not
independently executed.

Database commit order defines an exact race. If source replacement commits first, the
selection continues that latest mention. If selection commits first, it continues the
claim source visible in that transaction, and the later mention observes the committed
setting and follows normal configured admission. Any old or newly rendered setup
control resolves the current claim rather than retaining a stale message owner.

This decision supersedes the first-mention ownership portion of
`conversation-260801/ADR-D3` and the immutable first-source portion of
`conversation-260801/ADR-D4`. Their single-claim, single-continuation, shared-control,
and authority-separation rules remain accepted.

This decision applies to `conversation-260801/REQ-2`, `REQ-3`, `REQ-4`, and `REQ-14`.

Keeping the first eligible mention as the permanent owner is rejected because a setup
prompt may remain pending while more relevant requests arrive, leaving the eventual
Agent run attached to stale conversation intent. Releasing every retained mention
remains rejected because it could fan one setup completion into multiple Sessions and
AgentRuns.

### conversation-260801/ADR-D6 — Settings default new Bindings and Bindings own execution

The Agent-channel setting stores one required parent response-mode default. The first
setting created by setup snapshots the routed Agent's current External Channel default.
Every later Binding created for that Agent-channel relationship copies the setting's
current mode and retains it as a required concrete value.

For Channel location, ingestion evaluates only the connected parent-channel Binding's
concrete mode. A provider-native parent settings mutation atomically updates both the
Agent-channel setting and the currently connected parent-channel Binding. If no
parent-channel Binding exists, the next eligible top-level mention creates one using
the setting's current mode.

For Threads location, a parent settings mutation changes only the setting default.
Each future thread Binding copies that value, while every existing thread Binding
retains its concrete mode. A trustworthy thread-scoped settings action updates only
that connected thread Binding.

Changing the Agent-level default later does not rewrite an existing Agent-channel
setting or any Binding. Setup and settings confirmation render the concrete setting
snapshot, including the provider-native `all_messages` guidance required by the
Requirements.

This decision applies to `conversation-260801/REQ-8`, `REQ-9`, `REQ-10`, `REQ-11`,
and `REQ-14`.

Dynamic request-time inheritance from the Agent-channel setting is rejected because it
would create a second execution authority and retroactively rewrite thread behavior.
Using different response-mode authorities for Channel and Threads is rejected because
location transitions without an active parent Binding would require implicit fallback
rules and provider-specific management branches.

### conversation-260801/ADR-D7 — Existing thread Bindings do not backfill settings

The migration creates no Agent-channel participation setting from an existing
connected or disconnected thread Binding. Existing thread Resources, Bindings,
Sessions, concrete response modes, lifecycle timestamps, provider messages, and
projected Session history remain unchanged.

An exact existing connected thread Binding continues to win conversation resolution
and operate without a setup choice. A new top-level invocation for the same Agent and
provider parent channel has no implied location setting and therefore enters the
first-mention setup flow. A disconnected historical Binding never implies current
configuration or bypasses setup.

When a participant later completes setup, the new setting snapshots the routed
Agent's then-current External Channel response-mode default according to
`conversation-260801/ADR-D6`. Migration does not invent configuration provenance or
choose a future-thread default from potentially different historical Binding modes.

This decision applies to `conversation-260801/REQ-1`, `REQ-7`, `REQ-8`, `REQ-11`, and
`REQ-15`.

Backfilling Threads settings is rejected because it would turn prior implicit
thread-only behavior into an explicit shared choice that no provider participant
made. Lazy inference is rejected because message arrival order and an arbitrary
existing Binding could determine parent-channel behavior during rollout.

### conversation-260801/ADR-D8 — Terminal relationship loss invalidates settings without revival

Removing a route from a Multi App, deleting or decommissioning its Agent, or
terminally disconnecting the provider connection invalidates every active
Agent-channel setting owned by that relationship. The same lifecycle transaction
expires pending setup claims and interactions and applies the existing terminal
Binding cleanup. Sessions, provider Resources, invalidated settings, and history
remain retained records.

Re-enabling the same preserved route does not reactivate an invalidated setting,
pending setup, or disconnected Binding. A later eligible top-level mention creates a
new setup claim and requires a new explicit provider choice. A successful selection
creates a new active setting and, according to the selected location, later creates a
new Binding and Session rather than restoring terminal state.

Transient connection health such as `degraded` or `reconnect_required` does not
invalidate settings. Those states temporarily restrict applicable ingress or mutation
operations through the existing connection authority and resume the same setting
after recovery.

This decision applies to `conversation-260801/REQ-1`, `REQ-3`, `REQ-5`, `REQ-13`, and
`REQ-15`.

Automatically restoring a dormant setting is rejected because an old Channel and
`all_messages` choice could silently resume after a relationship administrator
re-enables the route. Offering a special restoration choice is rejected because the
participant must already complete a provider-native confirmation and can make a new
current selection without reviving stale lifecycle state.

### conversation-260801/ADR-D9 — Setup controls are re-surfaceable projections of one claim

The pending setup claim remains canonical independently from any one provider message
or interaction token. Each later eligible explicit mention may replace the
continuation source according to `conversation-260801/ADR-D5` and commit a fresh
setup-control projection near that latest provider message. A trustworthy Slash
Command or message-context action may also create a fresh interaction and reopen the
same claim.

Every old and new setup control revalidates the current provider actor, connection,
route, Agent lifecycle, scope, block, open-access or grant authority, setup claim, and
current Agent-channel setting before acting. A pending claim opens its current
choices. A completed claim or stale control shows the committed current setting and
never creates another setting, replay, Session input, or AgentRun. An expired or
invalidated claim returns a clear provider-native result; a later eligible mention
may create a new setup claim when the Agent-channel relationship is still
unconfigured and routable.

Known not-attempted or safely retryable control delivery may receive bounded recovery.
An ambiguous provider create outcome is not blindly retried; the next eligible
mention, command, or context action creates a fresh control projection referencing
the same claim. Provider-specific delivery attempts and outcomes remain evidence
rather than setup or execution authority.

Once a selection transaction commits the setting and continuation boundary,
confirmation-control delivery cannot roll back the setting, canonical mailbox input,
Session wake, or AgentRun. Provider confirmation and cleanup converge independently
through the current claim and setting generation.

This decision applies to `conversation-260801/REQ-2`, `REQ-3`, `REQ-4`, `REQ-9`,
`REQ-12`, and `REQ-14`.

A one-attempt-only prompt is rejected because delivery loss or provider timeline
movement could leave the shared setup undiscoverable. A provider-pinned control is
rejected because Slack and Discord cannot provide one portable permission and
lifecycle contract, and modifying a retained message does not move it to current
conversation context.

### conversation-260801/ADR-D10 — One selected Agent owns each provider parent channel

One provider connection and parent channel have at most one selected Agent route and
one active participation setting. A Single App's sole route is selected implicitly. A
Multi App uses its active channel default as the selected route. When an unconfigured
Multi App channel has no default, the provider-native Agent selector may establish one
route from only the Agents the current participant may invoke before
conversation-location setup continues.

The active setting identity is `(connection_id, provider_parent_channel_id)`. It
retains a restrictive `route_id` reference that must match the current selected route,
but the route is no longer part of active-setting cardinality. The setting remains a
separate record because conversation location, response-mode default, generation,
provider-principal provenance, and invalidation are not route-selection fields.

An eligible top-level message is never fanned out across Multi App routes. An ordinary
message may continue only the selected Agent's connected parent-channel Binding when
its concrete mode is `all_messages`. An explicit provider invocation resolves only one
selected Agent through the existing binding, channel default, or selector boundary.
Other explicitly selected Agents may continue to own isolated thread Bindings in the
same provider channel.

Replacing the selected Multi App Agent from route A to route B atomically invalidates
A's participation setting, expires its pending setup claim and current setup
interactions, and terminally disconnects only A's connected parent-channel Binding.
A's Session and history remain, and all existing thread Bindings remain unchanged.
Route B receives no transferred location, response mode, Binding, or Session. Its next
eligible top-level mention starts a new setup.

Clearing the Multi App channel default applies the same route-A cleanup without
installing route B. The channel then has no selected Agent, active participation
setting, parent Binding, or effective conversation location. Session history and every
thread Binding remain. A later provider-native or Web Agent selection establishes a
new channel default before location setup resumes.

This decision supersedes the active-setting identity and multiple independent
parent-settings portions of `conversation-260801/ADR-D1`. D1's separate setting
lifecycle root, restrictive route reference, Agent snapshot, and Single/Multi shared
model remain accepted. It also removes the later multi-Agent parent-channel fan-out
question before the Design begins.

This decision applies to `conversation-260801/REQ-1`, `REQ-2`, `REQ-5`, `REQ-6`,
`REQ-9`, `REQ-10`, `REQ-13`, and `REQ-15`.

Allowing several active Channel Agents is rejected because it contradicts the existing
one-route Multi App channel default and would make an unaddressed provider message
ambiguous. Routing ordinary traffic only to one default while retaining additional
`all_messages` settings is rejected because those settings would not describe their
effective behavior.

## Existing Authorities Preserved

- PostgreSQL External Channel conversation positions remain the sole durable provider
  read-through ordering and duplicate-prevention authority.
- Canonical mailbox identity remains the accepted-input and wake-recovery authority;
  provider callbacks and controls do not become a parallel execution queue.
- External Channel principals remain provider provenance and invocation authorization,
  never Azents execution Users.
- A Binding remains the concrete connected execution relationship and response-mode
  authority. A terminally disconnected Binding is never reactivated, and its Session
  history remains.
- The Multi App channel default remains route-selection authority only.
- Existing connected thread Bindings retain their Resource identity, Session, concrete
  response mode, lifecycle state, and history.

## Risks to Resolve

- Overloading the Multi App route default would make route selection and conversation
  behavior one ambiguous authority and prevent two Agents from having independent
  settings in the same provider channel.
- Reusing a thread Resource for parent-channel participation would merge incompatible
  provider scope and delivery semantics.
- Allowing more than one pending setup replay owner could fan one location choice into
  duplicate Sessions or AgentRuns, especially when `Threads` is selected.
- Dynamic response-mode inheritance would contradict the existing concrete-Binding
  invariant and create request-time policy ambiguity.
- Automatically restoring an old channel setting after route re-enable could revive
  channel-wide `all_messages` participation without a new explicit participant choice.
- One-attempt setup-control loss could strand the original mention before any canonical
  Session input exists.
