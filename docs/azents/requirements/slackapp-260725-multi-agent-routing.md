---
title: "Multi-Agent Slack App Routing Requirements"
created: 2026-07-25
updated: 2026-07-25
tags: [slack, external-channel, agent, frontend, security]
document_role: primary
document_type: requirements
snapshot_id: slackapp-260725
---

# Multi-Agent Slack App Routing Requirements

- Snapshot: `slackapp-260725`
- Document reference: `slackapp-260725/REQ`

## Problem

The current Slack integration is configured around a dedicated Agent, which makes a
single-Agent Slack App straightforward but cannot provide several Azents Agents
through one installed Slack App. Treating every Slack App as one Workspace-managed
integration would add unnecessary administration and ownership changes for Agent
administrators who only need one App for one Agent.

Slack participants need to discover and explicitly select among the Agents offered by
a shared Slack App, while Agent administrators need a distinct single-Agent setup
whose lifecycle remains owned from the Agent. Workspace administrators need a
separate multi-Agent App experience with reusable App management and channel
defaults. Messages must never be routed to the wrong Agent, and selecting another
Agent must not silently replace an established Slack-thread session.

## Product Modes

- A **Single App** is owned through one Agent's administration, can offer exactly that
  one Agent, and is removed when its Agent association is removed.
- A **Multi App** is owned through Workspace administration, may offer zero, one, or
  many Agents, and remains connected independently from any one Agent association.
- Single App and Multi App creation and management are separate user experiences.
  Users are not required to choose a technical App mode in one combined setup flow.

## Primary Actor

A Slack workspace participant who wants to use a specific Azents Agent from a channel
message through a Slack App that offers multiple Agents.

Supporting actors are an Agent administrator who owns a Single App through an Agent
and a Workspace Slack administrator who owns a Multi App and its channel defaults.

## Primary Scenario

1. A Workspace Slack administrator connects one Multi App and makes multiple Azents
   Agents available through it.
2. A Slack participant posts a normal channel message, including any relevant files,
   and opens the message shortcut for asking an Azents Agent.
3. Slack presents every Agent made available through that App, distinguishing Agents
   that can be used immediately from Agents that require access approval.
4. The participant selects an Agent. If approval is required, Azents preserves the
   original message and attachments until approval completes.
5. Azents links the Slack thread to the selected Agent and a new Agent Session, then
   delivers the original request without requiring the participant to rewrite it.
6. All later eligible messages and files in that Slack thread continue to the same
   Agent Session without another mention or Agent selection.
7. Selecting another Agent never replaces the existing thread binding; a separate
   Slack conversation is started for the other Agent.

## Supporting Scenarios

- An Agent administrator connects and manages a Single App without leaving the Agent
  workflow. The App is assigned to that Agent automatically, cannot be assigned to a
  second Agent, and is removed when the Agent association is removed.
- A Workspace Slack administrator starts from Multi App management, connects an App,
  and assigns zero, one, or many Agents. A Multi App with no assigned Agent remains
  connected and is visibly marked as needing setup.
- A Single App routes eligible unbound conversations to its sole Agent without
  presenting a multi-Agent catalog.
- A channel with a default Agent routes an eligible App mention to that Agent without
  an Agent-selection step.
- A channel without a default Agent presents the Agent selector when the App is
  mentioned.
- An authorized administrator manages the same channel default from either Slack or
  Azents.
- An existing dedicated Agent Slack connection is upgraded to the reusable model
  without Slack reinstallation, credential re-entry, or loss of existing thread and
  Session continuity.

## Goals

- Preserve a distinct Agent-admin-owned Single App experience for one Agent.
- Let a Workspace-admin-owned Multi App offer multiple explicitly associated Agents.
- Let one Agent be offered through multiple Single Apps and Multi Apps.
- Keep Agent-first Single App setup separate from Workspace-level Multi App
  administration.
- Provide explicit Agent selection through a Slack message shortcut.
- Support channel defaults without requiring every channel to be configured before
  use.
- Preserve access approval, source-message attachments, and immutable thread-to-Agent
  routing.
- Upgrade existing dedicated Agent connections without user-visible disruption.

## Non-Goals

- Automatically selecting an Agent by interpreting request content.
- Connecting multiple Agents to the same Slack thread at the same time.
- Replacing the Agent assigned to an established Slack thread.
- Automatic Agent handoff or delegation.
- Sharing one Slack App integration across different Azents Workspaces.
- Converting an existing Single App into a Multi App or transferring its existing
  conversation identities into a new Multi App.
- Expanding support to Slack direct messages or group direct messages.
- Changing Slack message edit or deletion lifecycle behavior.
- Giving each Agent a separate Slack bot user or bot name within one App.
- Recommending Agents from prior selections or maintaining a personal default Agent.
- Discovering or exposing Agents that are not explicitly associated with the Slack
  App.

## Requirements

### REQ-1. Workspace-owned Multi App management

A Workspace administrator must be able to create and manage a Multi App independently
from any single Agent.

**Acceptance criteria**

- Only a user with the required Workspace administration authority can create a Multi
  App.
- Multi App installation, connection health, credential replacement, reconnection,
  and disconnection remain manageable when no Agent is associated with the App.
- A connected Multi App with no associated Agent is visibly identified as needing
  Agent assignment.
- The management surface shows the Agents currently offered through the App and the
  channels with configured defaults.
- Slack credentials and connection lifecycle are not duplicated independently in
  each associated Agent's settings.

### REQ-2. Mode-specific Slack App and Agent availability

Administrators must be able to make one Agent available through multiple Apps while
preserving the one-Agent limit of a Single App and the shared catalog of a Multi App.

**Acceptance criteria**

- A Single App is associated with exactly one Agent and cannot accept a second Agent
  association.
- A Multi App can be associated with zero, one, or many Agents in the same Azents
  Workspace.
- One Agent can be associated with multiple Apps in the same Workspace.
- A Multi App's Agent catalog is derived from the Agents currently associated with
  that App.
- An Agent that is not associated with a Multi App never appears in that App's Agent
  selector.
- Single App and Multi App ownership and management are presented through separate
  product surfaces.

### REQ-3. Agent-admin-owned Single App setup

An Agent administrator must be able to create and manage a Single App directly from
Agent settings without Workspace integration administration.

**Acceptance criteria**

- Agent settings provide the Single App connection and management entry point.
- An Agent administrator can register a new Single App by supplying its Slack App
  identity and credentials.
- Completing Single App setup automatically associates the App with the current
  Agent.
- Every current administrator of the Agent can manage the Single App connection; its
  ownership is not permanently assigned to the individual who entered the
  credentials.
- Removing the Single App's Agent association also removes the App connection and
  makes its existing Slack conversations unavailable without rerouting them.
- The simple single-Agent setup does not require additional navigation compared with
  the existing dedicated Agent setup.

### REQ-4. Workspace-admin-owned Multi App setup

A Workspace Slack administrator must be able to connect a Multi App first and then
manage its Agent catalog independently from Agent settings.

**Acceptance criteria**

- Workspace integration management provides a Multi App connection flow independent
  of an Agent page.
- A user who only administers an Agent cannot create a Multi App without the required
  Workspace authority.
- The administrator can select multiple Agents during or after setup.
- The administrator can complete connection setup without selecting an Agent.
- A zero-Agent Multi App remains connected but visibly reports that Agent assignment
  is required before Agent invocation can succeed.
- Removing one Agent association does not disconnect the Multi App or affect its
  other Agent associations.
- Multi App assignments are visible from the relevant Agent context without moving
  App ownership or lifecycle management into Agent settings.

### REQ-5. Agent catalog visibility and access state

A Slack participant must be able to see every Agent associated with a Multi App while
remaining subject to each Agent's access policy. A Single App uses its sole Agent
without presenting a multi-Agent catalog.

**Acceptance criteria**

- The Multi App Agent selector lists every active Agent associated with the App.
- The selector distinguishes Agents the participant may use immediately from Agents
  marked `Access required`.
- An Agent requiring approval cannot execute for the participant before approval.
- Selecting an `Access required` Agent starts the existing participant approval
  experience rather than hiding the Agent.
- Inactive or removed Agents cannot be selected for a new conversation.

### REQ-6. Explicit Agent selection from a Slack message

A Slack participant must be able to start a Multi App Agent conversation from an
existing visible Slack message by explicitly selecting an Agent.

**Acceptance criteria**

- The message action menu exposes an `Ask an Azents Agent` shortcut for eligible
  messages.
- The selection flow retains the selected Slack message as the request source.
- Text and supported attachments from the selected message are delivered to the
  selected Agent conversation.
- The participant is not required to copy or rewrite the request after selecting an
  Agent.
- The selected Agent is visibly identified when the Slack conversation starts.

### REQ-7. Channel default Agent management

An authorized Workspace administrator must be able to configure a default Agent
independently for every channel in which a Multi App is used.

**Acceptance criteria**

- A channel default can be viewed and changed from both Slack and Azents.
- Both management surfaces show the same effective default.
- Only an Agent currently associated with the Slack App can be selected as the
  channel default.
- Changing the default affects future unbound conversations and does not reroute an
  existing bound thread.
- Slack channel membership has no product-configured maximum imposed by this feature.
- Only a user authorized to manage the Workspace Slack App can change a channel
  default; ordinary channel participation is insufficient.

### REQ-8. Unconfigured-channel Agent selection

A Slack participant must still be able to use a Multi App in a channel that has no
default Agent.

**Acceptance criteria**

- Mentioning the App in an unbound channel conversation with no default opens an
  Agent-selection experience rather than failing silently.
- The selector contains the Agents associated with the App and their access states.
- Selecting an Agent applies to the new Slack-thread conversation and does not
  silently create a channel default.
- A separately authorized administration action may save an Agent as the channel
  default.

### REQ-9. Immutable Slack-thread Agent binding

Each linked Slack thread must have exactly one Agent and one Agent Session as its
conversation destination.

**Acceptance criteria**

- The first accepted default or explicit Agent selection creates one binding to the
  selected Agent and a new Agent Session.
- Later eligible messages and files in the linked thread reach the same Session
  without requiring another mention.
- Duplicate or concurrent selection attempts cannot create multiple active Agent
  destinations for the same Slack thread.
- Selecting another Agent for an already linked thread does not replace the existing
  Agent or Session.
- The user is offered a separate Slack conversation when another Agent is requested.

### REQ-10. Approval continuity for selected requests

Agent access approval must not lose the request that caused the participant to select
the Agent.

**Acceptance criteria**

- The selected source message and supported attachments remain retained while
  approval is pending.
- Approval does not create an Agent run before access is granted.
- Successful approval resumes the selected request without requiring the participant
  to submit it again.
- Denial or blocking prevents execution according to the existing participant access
  policy.
- Repeated approval callbacks cannot execute the same retained request more than
  once.

### REQ-11. Mode-specific relationship-change safety

Changing Agent availability, App ownership scope, or channel defaults must never
silently route a Slack conversation to a different Agent.

**Acceptance criteria**

- Removing the sole Agent association from a Single App also removes the Single App
  connection.
- Removing an Agent from a Multi App removes it from new Agent-selection experiences
  without disconnecting the Multi App or its other Agent associations.
- A channel default that no longer identifies an eligible Agent is shown as
  unconfigured rather than falling back silently to another Agent.
- Existing Slack-thread bindings affected by either removal become explicitly
  unavailable while retaining an unambiguous recorded Agent and Session identity.
- Administrators are shown the affected channel defaults and active bindings before
  a relationship-changing action is confirmed.
- No relationship change grants a participant access to another Agent.

### REQ-12. Existing dedicated connection continuity

Existing dedicated Agent Slack connections must upgrade to the Single App model
without user action or conversation loss.

**Acceptance criteria**

- Existing Slack Apps do not require reinstallation or reauthorization.
- Existing credentials do not require re-entry.
- Each existing connection becomes an Agent-admin-owned Single App and remains
  associated with its existing Agent.
- Existing channel resources, Slack-thread bindings, Agent Sessions, participant
  access state, pending requests, and imported message history remain intact.
- Existing single-Agent Slack behavior remains observably unchanged after migration.
- An existing App without Slack message-customization capability continues using its
  default bot icon and does not require reauthorization solely for Agent imagery.
- The upgraded connection appears in the Agent's Single App management experience
  without being presented as a Workspace-owned Multi App.

### REQ-13. Routing isolation and authorization safety

Multi-Agent routing must not cross Agent, Slack App, Workspace, channel, thread, or
participant authorization boundaries.

**Acceptance criteria**

- An inbound Slack message is matched to the App installation that received it before
  Agent selection or thread routing occurs.
- A linked thread routes only to its recorded Agent Session.
- A participant's access to one Agent does not grant access to another Agent shown by
  the same App.
- An Agent association in one App does not expose the Agent through another App
  unless that second association is explicitly configured.
- A Slack App in one Azents Workspace cannot select Agents from another Azents
  Workspace.
- Ambiguous, missing, or invalid routing state fails without invoking an Agent.

### REQ-14. Minimal selected Agent presentation

Every Agent-authored Slack output must identify the Agent without replacing the
shared Slack bot user or bot name.

**Acceptance criteria**

- The first visible content in every Agent-authored Slack output is the Agent name in
  bold.
- When the Agent has an image and the Slack App has message-customization capability,
  the output overrides the message icon with that Agent image.
- A missing Agent image, unusable image, or missing customization capability falls
  back to the Slack App's default bot icon without blocking delivery.
- The Slack bot user and bot name remain unchanged.
- No additional Agent banner, connection notice, product label, description, status
  badge, or retained presentation snapshot is required.

## Fixed Constraints

- A Single App is Agent-admin-owned, has exactly one Agent, and is removed with that
  Agent association.
- A Multi App is Workspace-admin-owned, may have zero or more Agents, and remains
  connected independently from any one Agent.
- Single App and Multi App setup and management are separate user experiences.
- A Single App cannot be converted or transferred into a Multi App. A Workspace
  administrator creates a separate Multi App connection when shared use is required.
- Only a user with the required Workspace authority can create a Multi App.
- One Slack thread has at most one active Agent and Agent Session destination.
- Existing participant approval and blocking remains Agent-specific.
- Existing Slack message edit and deletion lifecycle behavior is unchanged by this
  snapshot.
- The Slack App uses one provider bot user and bot name. Agent-authored output starts
  with the bold Agent name and may override only the message icon when capability is
  available.
- Existing dedicated Agent connections must migrate without Slack reinstallation,
  credential re-entry, or loss of existing conversation continuity.

## Open Assumptions

- Slack message shortcuts and interactive selection surfaces remain available for the
  installed Multi App configuration.
- The existing participant approval flow can retain and later release a shortcut- or
  mention-originated request without introducing Slack-to-Azents account linking.

## Confirmation

The original Requirements were confirmed by the requester on 2026-07-25. The
requester revised the ownership and setup contract on 2026-07-25 to separate
Agent-admin-owned Single Apps from Workspace-admin-owned Multi Apps while retaining
the previously confirmed multi-Agent selection, approval, binding, and migration
goals. The requester explicitly confirmed this complete revised snapshot on
2026-07-25 before the ADR was reconciled. The requester subsequently confirmed that a
Single App cannot be converted or transferred into a Multi App and chose the minimal
Agent presentation contract in `slackapp-260725/REQ-14`.
