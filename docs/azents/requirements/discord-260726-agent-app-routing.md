---
title: "Discord Agent App Routing Requirements"
created: 2026-07-26
updated: 2026-07-26
tags: [discord, external-channel, agent, frontend, files, security]
document_role: primary
document_type: requirements
snapshot_id: discord-260726
---

# Discord Agent App Routing Requirements

- Snapshot: `discord-260726`
- Document reference: `discord-260726/REQ`

## Problem

Azents supports complete Single App and Multi App Agent conversations through Slack,
but Discord participants cannot use the same Agents, routing controls, approval flow,
files, and conversation continuity from a Discord server. A reduced Discord integration
would create different ownership, safety, and user expectations depending on the
provider.

Discord participants need the same observable Agent experience that Slack participants
have. Agent administrators need a distinct one-Agent setup, Workspace administrators
need shared multi-Agent App management and channel defaults, and every conversation
must remain isolated to the explicitly resolved Agent and Agent Session.

This snapshot fixes the parity baseline to the Slack External Channel behavior available
on 2026-07-26 and enumerated below. Later Slack changes do not silently expand or alter
this confirmed Discord scope.

## Product Modes

- A **Single App** is owned through one Agent's administration, offers exactly that one
  Agent, and is removed when its Agent association is removed.
- A **Multi App** is owned through Workspace administration, may offer zero, one, or
  many Agents, and remains connected independently from any one Agent association.
- Single App and Multi App creation and management are separate user experiences.
  Administrators are not required to choose a technical App mode in one combined flow.

## Primary Actor

A Discord server participant who wants to use a specific Azents Agent from a server
channel through a Discord App that offers multiple Agents.

Supporting actors are an Agent administrator who owns a Single App through an Agent
and a Workspace Discord administrator who owns a Multi App and its channel defaults.

## Primary Scenario

1. A Workspace Discord administrator connects one Multi App to a Discord server and
   makes multiple Azents Agents available through it.
2. A Discord participant posts a normal server-channel message, including any relevant
   files, and invokes the Discord-native equivalent of Slack's message action for asking
   an Azents Agent.
3. Discord presents every Agent made available through that App, distinguishing Agents
   that can be used immediately from Agents that require access approval.
4. The participant selects an Agent. If approval is required, Azents preserves the
   original message and attachments until approval completes.
5. Azents links the Discord conversation to the selected Agent and a new Agent Session,
   then delivers the original request without requiring the participant to rewrite it.
6. All later eligible messages and files in that linked Discord conversation continue
   to the same Agent Session without another mention or Agent selection.
7. Selecting another Agent never replaces the established conversation binding; the
   participant must start a separate Discord conversation for the other Agent.

## Supporting Scenarios

- An Agent administrator connects and manages a Single App from Agent settings. The App
  is assigned to that Agent automatically, cannot be assigned to a second Agent, and is
  removed when the Agent association is removed.
- A Workspace Discord administrator connects a Multi App before assigning any Agent and
  later assigns zero, one, or many Agents.
- A Single App routes an eligible unbound Discord conversation to its sole Agent without
  presenting a multi-Agent catalog.
- A channel with a default Agent routes an eligible App mention to that Agent without an
  Agent-selection step.
- A channel without a default Agent presents the Agent selector when the App is
  mentioned.
- An authorized administrator manages the same channel default from either Discord or
  Azents.
- A participant supplies supported inbound files, and an Agent explicitly publishes
  supported Runtime or Exchange files in the linked Discord conversation.
- Duplicate Discord events, interactions, decisions, and delivery attempts converge on
  the same durable outcome without duplicate Agent execution or provider mutation.

## Goals

- Provide Discord-native equivalents for the complete confirmed Slack External Channel
  experience without weakening behavior, security, or validation scope.
- Preserve a distinct Agent-admin-owned Single App experience for one Agent.
- Let a Workspace-admin-owned Multi App offer multiple explicitly associated Agents.
- Let one Agent be offered through multiple Single Apps and Multi Apps.
- Provide explicit Agent selection from an existing Discord message.
- Support channel defaults without requiring every channel to be configured before use.
- Preserve access approval, source-message files, and immutable conversation-to-Agent
  routing.
- Support inbound and outbound file behavior equivalent to Slack.
- Keep Discord identity, callback actors, and delivery retries from changing canonical
  execution authority or producing duplicate work.

## Non-Goals

- Adding Discord-only Agent behavior that has no current Slack equivalent, including
  voice, stage, or forum-specific workflows.
- Requiring a Discord slash-command workflow when the equivalent Slack behavior does
  not require one.
- Automatically selecting an Agent by interpreting request content.
- Connecting multiple Agents to the same Discord conversation at the same time.
- Replacing the Agent assigned to an established Discord conversation.
- Automatic Agent handoff or delegation.
- Sharing one Discord App integration across different Azents Workspaces.
- Converting an existing Single App into a Multi App.
- Supporting Discord direct messages or group direct messages.
- Introducing new message edit or deletion lifecycle behavior.
- Giving each Agent a separate Discord bot identity within one App.
- Recommending Agents from prior selections or maintaining a personal default Agent.
- Discovering or exposing Agents that are not explicitly associated with the Discord
  App.
- Transferring an established conversation between Slack and Discord.
- Migrating legacy Discord connections; no prior Azents Discord integration exists in
  this snapshot's baseline.

## Requirements

### REQ-1. Observable Slack parity

A Discord participant or administrator must be able to complete the corresponding
Discord workflow for every Slack External Channel behavior fixed by this snapshot.

**Acceptance criteria**

- Every behavior required below has a Discord-native user interaction and observable
  outcome.
- A Discord platform limitation may change control shape or interaction timing but may
  not silently remove a required outcome.
- Any parity behavior that is infeasible under Discord's platform contract is returned
  for explicit requirement review rather than omitted during design or implementation.
- Discord-specific additions outside the enumerated parity baseline require a later
  Requirements snapshot.

### REQ-2. Workspace-owned Multi App management

A Workspace administrator must be able to create and manage a Discord Multi App
independently from any single Agent.

**Acceptance criteria**

- Only a user with the required Workspace administration authority can create a Multi
  App.
- Installation, connection health, credential replacement, reconnection, and
  disconnection remain manageable when no Agent is associated with the App.
- A connected Multi App with no associated Agent is visibly identified as needing Agent
  assignment.
- The management surface shows the Agents currently offered through the App and the
  Discord channels with configured defaults.
- Discord credentials and connection lifecycle are not duplicated independently in
  each associated Agent's settings.

### REQ-3. Mode-specific App and Agent availability

Administrators must be able to make one Agent available through multiple Discord Apps
while preserving the one-Agent limit of a Single App and the shared catalog of a Multi
App.

**Acceptance criteria**

- A Single App is associated with exactly one Agent and cannot accept a second Agent
  association.
- A Multi App can be associated with zero, one, or many Agents in the same Azents
  Workspace.
- One Agent can be associated with multiple Apps in the same Workspace.
- A Multi App's Agent catalog contains only its current explicit Agent associations.
- Single App and Multi App ownership and management use separate product surfaces.

### REQ-4. Agent-admin-owned Single App setup

An Agent administrator must be able to create and manage a Discord Single App directly
from Agent settings without Workspace integration administration.

**Acceptance criteria**

- Agent settings provide the Single App connection and management entry point.
- An Agent administrator can register a new Single App using the required Discord App
  identity and credentials.
- Completing setup automatically associates the App with the current Agent.
- Every current administrator of the Agent can manage the connection; ownership is not
  permanently assigned to the individual who entered credentials.
- Removing the Agent association also removes the App connection and makes its existing
  Discord conversations unavailable without rerouting them.
- The Single App flow does not require Multi App administration steps.

### REQ-5. Workspace-admin-owned Multi App setup

A Workspace Discord administrator must be able to connect a Multi App first and manage
its Agent catalog independently from Agent settings.

**Acceptance criteria**

- Workspace integration management provides a Multi App connection flow independent of
  an Agent page.
- A user who only administers an Agent cannot create a Multi App without the required
  Workspace authority.
- The administrator can select multiple Agents during or after setup.
- The administrator can complete connection setup without selecting an Agent.
- Removing one Agent association does not disconnect the App or affect its other Agent
  associations.
- Multi App assignments are visible from relevant Agent contexts without moving App
  lifecycle ownership into Agent settings.

### REQ-6. Agent catalog visibility and access state

A Discord participant must be able to see every active Agent associated with a Multi
App while remaining subject to each Agent's access policy. A Single App uses its sole
Agent without presenting a multi-Agent catalog.

**Acceptance criteria**

- The Multi App selector lists every active Agent associated with the App.
- The selector distinguishes immediately available Agents from Agents marked `Access
  required`.
- An Agent requiring approval cannot execute for the participant before approval.
- Selecting an `Access required` Agent starts the existing participant approval
  experience rather than hiding the Agent.
- Inactive, removed, or cross-Workspace Agents cannot be selected.

### REQ-7. Explicit Agent selection from a Discord message

A Discord participant must be able to start a Multi App Agent conversation from an
existing visible Discord message by explicitly selecting an Agent.

**Acceptance criteria**

- Eligible server-channel messages expose a Discord-native message action equivalent to
  Slack's `Ask an Azents Agent` shortcut.
- The selection flow retains the selected Discord message as the request source.
- Text and supported attachments from the selected message are delivered to the
  selected Agent conversation.
- The participant is not required to copy or rewrite the request.
- The selected Agent is visibly identified when the conversation starts.

### REQ-8. Channel default Agent management

An authorized Workspace administrator must be able to configure a default Agent
independently for every Discord channel in which a Multi App is used.

**Acceptance criteria**

- A channel default can be viewed and changed from both Discord and Azents.
- Both management surfaces show the same effective default.
- Only an Agent currently associated with the App can be selected as the default.
- Changing the default affects future unbound conversations and never reroutes an
  existing binding.
- Discord channel membership has no product-configured maximum imposed by this feature.
- Ordinary channel participation is insufficient to change the default.

### REQ-9. Unconfigured-channel Agent selection

A Discord participant must still be able to use a Multi App in a channel that has no
default Agent.

**Acceptance criteria**

- Mentioning the App in an eligible unbound channel conversation with no default opens
  an Agent-selection experience rather than failing silently.
- The selector contains the Agents associated with the App and their access states.
- Selecting an Agent applies to the new linked Discord conversation and does not
  silently create a channel default.
- A separately authorized administration action may save an Agent as the channel
  default.

### REQ-10. Immutable Discord conversation binding

Each linked Discord conversation must have exactly one Agent and one Agent Session as
its destination.

**Acceptance criteria**

- The first accepted default or explicit selection creates one binding to the selected
  Agent and a new Agent Session.
- Later eligible messages and files in the linked conversation reach the same Session
  without another mention.
- Duplicate or concurrent selection attempts cannot create multiple active Agent
  destinations.
- Selecting another Agent never replaces the existing Agent or Session.
- The participant is directed to start a separate Discord conversation when another
  Agent is requested.

### REQ-11. Approval continuity for selected requests

Agent access approval must not lose the Discord request that caused the participant to
select the Agent.

**Acceptance criteria**

- The selected source message and supported attachments remain retained while approval
  is pending.
- Approval does not create an Agent run before access is granted.
- Successful approval resumes the selected request without another submission.
- Denial or blocking prevents execution according to the existing participant access
  policy.
- Repeated approval callbacks cannot execute the retained request more than once.

### REQ-12. Mode-specific relationship-change safety

Changing Agent availability, App ownership scope, or channel defaults must never
silently route a Discord conversation to another Agent.

**Acceptance criteria**

- Removing the sole Agent association from a Single App also removes its connection.
- Removing an Agent from a Multi App removes it from new selection experiences without
  disconnecting the App or other associations.
- An invalidated channel default becomes visibly unconfigured rather than falling back
  to an arbitrary Agent.
- Affected existing bindings become explicitly unavailable while retaining their
  recorded Agent and Session identity.
- Administrators see affected defaults and active bindings before confirming a
  relationship-changing action.
- No relationship change grants access to another Agent.

### REQ-13. Routing isolation and authorization safety

Discord routing must not cross App installation, Azents Workspace, Discord server,
channel, conversation, Agent, Session, or participant authorization boundaries.

**Acceptance criteria**

- An inbound Discord event or interaction is matched to the receiving App installation
  before selection or conversation routing.
- A linked conversation routes only to its recorded Agent Session.
- Access to one Agent does not grant access to another Agent offered by the same App.
- An association in one App does not expose the Agent through another App.
- A Discord App in one Azents Workspace cannot select Agents from another Workspace.
- Ambiguous, missing, stale, tampered, or invalid routing state fails without invoking
  an Agent.
- Discord identity and the actor who triggers an interaction never determine the
  canonical Azents execution User.

### REQ-14. Discord interaction and retry safety

Discord events and interactive controls must acknowledge platform callbacks promptly
while preserving durable admission, idempotency, and at-most-once external effects.

**Acceptance criteria**

- Required Discord callbacks are acknowledged within the provider deadline even when
  Agent work continues asynchronously.
- Acknowledgement does not substitute for durable admission of work that must survive
  process failure.
- Duplicate event deliveries, component actions, modal submissions, and approval
  decisions converge on one durable outcome.
- Expired, replayed, cross-resource, or tampered interactions fail closed.
- Transient Discord interaction tokens or equivalent callback-only capabilities are
  not persisted or replayed as durable triggers.

### REQ-15. Message, Agent identity, and file parity

Discord conversations must preserve the same inbound message, Agent presentation, and
explicit outbound file behavior as Slack within Discord's supported message contract.

**Acceptance criteria**

- Supported inbound message text and attachments materialize under the same bounded,
  authorized External Channel file policy used for Slack.
- The first visible content in every Agent-authored output identifies the Agent name in
  bold.
- The App retains one shared Discord bot identity; an Agent image is used only when the
  provider supports a safe per-message override, with fallback to the App identity.
- Explicit `channel_action` replies accept the same authorized Runtime paths and
  `exchange://` files, limits, ordering, explanatory text requirement, and failure
  behavior as Slack.
- No file body, provider credential, transient upload URL, or participant content is
  persisted outside the existing bounded durable records.
- Provider rejection, unavailable files, and ambiguous delivery remain controlled
  failures and never report misleading success.

## Fixed Constraints

- Discord must match the Slack parity baseline enumerated in this snapshot; platform
  differences may change mechanics but not required outcomes without requester review.
- A Single App is Agent-admin-owned, has exactly one Agent, and is removed with that
  Agent association.
- A Multi App is Workspace-admin-owned, may have zero or more Agents, and remains
  connected independently from any one Agent.
- Single App and Multi App setup and management are separate user experiences.
- A Single App cannot be converted or transferred into a Multi App.
- One linked Discord conversation has at most one active Agent and Agent Session
  destination.
- Existing participant approval and blocking remains Agent-specific.
- PostgreSQL remains the canonical source of truth; provider callbacks, Gateway events,
  and brokers only route or wake durable work.
- Durable mutations are fenced by canonical ownership generation where the equivalent
  Slack flow is generation-fenced.
- Discord identity and callback actors are provenance only and never inferred as the
  execution User.
- The App uses one provider bot identity. Agent-authored output identifies the Agent
  without requiring one bot identity per Agent.
- Delivery remains commit-before-provider-call and avoids replaying ambiguous external
  mutations.
- Git-tracked implementation, documentation, PR text, and examples are in English.

## Open Assumptions

- Discord provides install, server-event, message-action, component, selection, and
  modal capabilities sufficient to represent the enumerated flows with native controls.
- Required Discord permissions and privileged intents can be requested and clearly
  surfaced during setup without changing the confirmed ownership model.
- Discord platform limits may require pagination, deferred responses, or follow-up
  messages, but these mechanics do not reduce the required Agent catalog or continuity.
- The existing participant approval flow can retain and later release a Discord-origin
  request without Discord-to-Azents account linking.

## Confirmation

The requester explicitly confirmed this complete Requirements snapshot on 2026-07-26
by directing the Discord integration to preserve every enumerated Slack-equivalent
behavior before ADR and design decisions began.
