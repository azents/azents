---
title: "Provider Channel Participation Settings Requirements"
created: 2026-08-01
updated: 2026-08-01
implemented: 2026-08-02
tags: [external-channel, slack, discord, conversation]
document_role: primary
document_type: requirements
snapshot_id: conversation-260801
---

# Provider Channel Participation Settings Requirements

- Snapshot: `conversation-260801`
- Document reference: `conversation-260801/REQ`

## Problem

An External Channel mention currently starts an isolated conversation associated
with the addressed provider message or thread. Users cannot intentionally make an
Agent participate in the parent Slack or Discord channel as one continuing
conversation.

Automatically enabling channel-wide participation from an Agent-level default would
be unsafe. An Agent installed in several channels could begin reacting throughout all
of them, especially when its response mode is `all_messages`. Users need to choose
the behavior explicitly for the one Agent selected for each provider channel,
understand the effective response mode, and change the shared behavior without
leaving Slack or Discord.

## Primary Actor

An authenticated human Slack or Discord participant who currently has permission to
invoke the selected Agent in the provider conversation.

## Primary Scenario

1. The participant mentions the selected Agent in a provider channel that has no
   conversation location configured.
2. The Agent does not execute yet. The provider presents a shared setup action that
   asks whether replies should continue in the parent channel or in message threads.
3. Any human participant who currently has permission to invoke that Agent may
   complete the setup. The first valid completion becomes the selected channel
   Agent's conversation default.
4. The original mention is processed with its original author and message provenance
   in the selected location.
5. The provider confirms the selected conversation location and the response mode
   inherited from the Agent. When the mode is `all_messages`, the confirmation
   explains how to switch to `mention_only` if the Agent feels too chatty.
6. Later messages follow the saved selected-Agent channel behavior until an
   authorized participant changes it through a provider-native settings action.

## Supporting Scenarios

- An authorized participant changes the parent channel's conversation location or
  response mode through a Slack or Discord command or action.
- A channel using thread conversations applies its channel response mode only to
  thread bindings created later. Existing thread bindings retain their concrete
  response modes.
- An authorized participant changes one existing thread binding's response mode
  through any trustworthy thread-scoped command, binding control, or message-context
  action supported by that provider.
- In a Multi App channel with no selected default Agent, the participant selects one
  Agent from only the routes they may invoke before choosing conversation behavior.
  That Agent becomes the channel's sole selected Agent.
- Replacing a Multi App channel's selected Agent disconnects the old parent-channel
  Binding and invalidates its conversation setting without changing existing thread
  Bindings or deleting Session history.
- Concurrent setup or settings actions converge on one current selected-Agent channel
  configuration without changing the original message author or creating duplicate
  conversations.

## Goals

- Let users deliberately choose persistent channel participation or isolated thread
  conversations for the one Agent selected for each provider channel.
- Keep first-time activation and later settings changes inside Slack or Discord.
- Reuse the existing Agent response-mode default when the first binding is created.
- Let every provider participant who may invoke an Agent manage that Agent's shared
  channel behavior.
- Prevent implicit channel-wide activation and preserve existing conversation history
  when behavior changes.
- Provide a reliable way to manage an existing thread response mode even when the
  provider does not support Slash Commands inside threads.

## Non-Goals

- Providing an Agent-level default for channel versus thread conversation location.
- Automatically activating channel participation when an App is installed or an
  Agent route becomes available.
- Asking users to choose or attach an existing Azents Session.
- Requiring Web management to complete the primary setup or settings workflow.
- Combining provider threads into the parent channel Session.
- Rewriting every existing thread binding when a channel default changes.
- Requiring Slack and Discord to expose identical control types when their native
  interaction capabilities differ.
- Mapping an External Channel participant to an Azents User for execution authority.

## Requirements

### REQ-1. No implicit conversation-location default

A provider channel's selected Agent has no effective channel-versus-thread
conversation location until an authorized participant explicitly chooses one.

**Acceptance criteria**

- Installing or associating an Agent does not create a channel Session or Binding.
- Agent configuration does not automatically select `channel` or `threads` for every
  provider channel.
- Existing connected thread bindings continue operating without requiring a new
  selection.

### REQ-2. First-mention setup gate

The first eligible mention for an unconfigured selected-Agent channel must request a
conversation-location selection before Agent execution begins.

**Acceptance criteria**

- The setup offers user-facing choices equivalent to `Answer in this channel` and
  `Answer in a thread`.
- Before a valid selection, the mention creates no runnable Session input, AgentRun,
  or active conversation Binding.
- Repeated or concurrent unconfigured mentions do not create multiple active
  configurations or Sessions.

### REQ-3. Shared setup authorization and provenance

Any authenticated human participant who could currently invoke the selected Agent in
that provider conversation may complete the shared setup.

**Acceptance criteria**

- Active blocks deny setup.
- Existing open-access and grant rules determine eligibility for the selected Agent.
- The first valid concurrent selection wins; later actions show the current setting
  or may change it through the normal settings flow.
- The participant who completes setup does not replace the original mention author,
  message identity, or execution provenance.

### REQ-4. Original-mention continuation

After setup succeeds, the original mention must continue in the selected conversation
location without requiring the participant to send it again.

**Acceptance criteria**

- `Channel` processes the original top-level mention through the Agent-channel
  conversation.
- `Threads` processes the original mention through an isolated message-thread
  conversation.
- While setup remains pending, each later eligible explicit mention becomes the
  continuation source. Earlier mentions may remain bounded provider-history context
  but are not independently executed.
- Retries converge without duplicate Session input or duplicate Agent execution.

### REQ-5. One selected Agent and setting per provider channel

Conversation settings belong to one provider connection and provider parent channel,
and reference that channel's one currently selected Agent route.

**Acceptance criteria**

- A Multi App may contain many Agent routes, but each provider parent channel has at
  most one currently selected Agent route.
- An unconfigured Multi App channel may select one Agent through a provider-native
  route selector before conversation-location setup.
- The active conversation setting references the same Agent route as the channel's
  active route default.
- Replacing the channel's selected Agent invalidates the old conversation setting and
  does not transfer its location or response mode to the new Agent.
- Clearing the channel's selected Agent invalidates the old conversation setting and
  leaves the parent channel without an effective Agent or conversation location.
- The same Agent may have different settings in different provider channels.
- Existing thread Bindings may continue using other explicitly selected Agents and are
  not rewritten when the parent channel's selected Agent changes.

### REQ-6. Channel conversation behavior

When `Channel` is selected, the Agent uses one connected Session for eligible
top-level messages in that parent channel.

**Acceptance criteria**

- Later eligible top-level messages reuse the connected channel Session.
- Agent conversational replies are delivered to the parent channel rather than an
  automatically created reply thread.
- Provider thread messages are not merged into the parent channel Session.
- A mention inside a provider thread continues to use an isolated thread
  conversation.

### REQ-7. Thread conversation behavior

When `Threads` is selected, each newly addressed provider thread remains an isolated
conversation with its own connected Binding and Session.

**Acceptance criteria**

- A new top-level mention starts or targets only its own provider thread conversation.
- Sibling top-level messages do not reuse another thread's Session.
- Changing the channel default does not rewrite existing connected thread bindings.

### REQ-8. Existing response-mode default

The first Binding created after conversation-location setup must use the existing
Agent-level External Channel response-mode default.

**Acceptance criteria**

- The concrete initial mode is `mention_only` or `all_messages` according to the
  Agent's current configured default.
- No new hard-coded response-mode default replaces the existing Agent policy.
- The setup confirmation displays the inherited response mode.
- When the inherited mode is `all_messages`, the confirmation gives one concise
  provider-native instruction for switching to `mention_only` if the Agent feels too
  chatty.

### REQ-9. Parent-channel settings

Authorized participants must be able to view and change the selected Agent's parent
channel conversation location and channel response-mode default through
provider-native settings.

**Acceptance criteria**

- The settings surface shows the selected Agent, conversation location, and response
  mode.
- The participant may change `Channel` versus `Threads`.
- The participant may change `mention_only` versus `all_messages`.
- Settings confirmation explains the resulting effective behavior.
- The primary flow does not require an Azents Web Session picker or administrator
  role.

### REQ-10. Response mode in Channel behavior

For an active channel Binding, changing the parent channel response mode changes that
Binding's admission behavior.

**Acceptance criteria**

- `mention_only` admits explicit Agent invocations and does not independently execute
  eligible ordinary messages.
- `all_messages` admits eligible ordinary top-level human messages for the connected
  channel Session.
- Provider threads remain outside the channel Session in either response mode.

### REQ-11. Response mode in Threads behavior

For `Threads`, the parent channel response mode is the default for thread bindings
created later, while each existing thread binding retains its concrete mode.

**Acceptance criteria**

- A new thread binding uses the current parent channel response-mode setting.
- Changing the parent channel response mode does not alter existing thread bindings.
- An existing thread binding may be changed independently when a trustworthy
  provider-native thread-scoped settings entry point is available.

### REQ-12. Capability-adaptive provider entry points

Each provider must expose every settings entry point it can safely scope, and all
entry points must converge on the same authorization and settings behavior.

**Acceptance criteria**

- A Slash Command invoked with trustworthy parent-channel context opens parent-channel
  settings.
- A Slash Command invoked with trustworthy thread context may open the current thread
  binding's response-mode settings.
- Every connected binding exposes a binding-scoped conversation-settings action with
  its Session navigation control.
- Slack and Discord expose a message-context settings action capable of resolving the
  selected message's parent-channel or thread conversation.
- A provider that cannot prove thread scope never changes the parent-channel setting
  as a fallback.

### REQ-13. Conversation-location transition

Changing an Agent-channel conversation location must stop obsolete routing without
deleting Session history.

**Acceptance criteria**

- `Channel` to `Threads` disconnects the current channel Binding.
- Disconnecting the Binding does not delete or archive its Session or history.
- Existing thread bindings remain connected.
- `Threads` to `Channel` does not create an empty Session; the next eligible top-level
  mention creates the new channel Binding and Session.
- A disconnected channel Binding is not reactivated; later channel activation creates
  a new Binding and Session.
- Replacing a Multi App channel's selected Agent disconnects only the old
  parent-channel Binding, invalidates its setting, preserves its Session history and
  every existing thread Binding, and leaves the new selected Agent unconfigured until
  a later eligible mention completes setup.
- Clearing a Multi App channel's selected Agent applies the same old-Agent cleanup,
  preserves Session history and thread Bindings, and requires a later Agent selection
  before conversation-location setup can resume.

### REQ-14. Shared-setting visibility

Participants must be able to understand the current shared behavior after setup or a
settings change.

**Acceptance criteria**

- Setup completion identifies the selected Agent, conversation location, and response
  mode.
- Settings actions show the current values before mutation and the resulting values
  after mutation.
- Guidance is shown on setup or settings completion, not repeated on ordinary Agent
  replies.
- Unsupported controls are omitted or return a clear provider-native unsupported
  result rather than silently changing another scope.

### REQ-15. Existing behavior compatibility

Existing connected External Channel bindings and their Session history must remain
valid when the capability is introduced.

**Acceptance criteria**

- Existing thread bindings retain their resource identity, Session, concrete response
  mode, and connected or disconnected lifecycle state.
- Existing provider messages and Session events are not rewritten into channel
  conversations.
- Existing Agent response-mode defaults remain configurable through their current
  management authority.

## Fixed Constraints

- Initial scope and later settings management support both Slack and Discord.
- Provider credentials, callback tokens, raw interaction payloads, message bodies,
  and transient provider URLs are not retained as settings evidence.
- Provider participants remain External Channel principals and never become Azents
  execution Users.
- Settings changes revalidate the current provider actor, Agent route, conversation
  scope, block state, and open-access or grant authority.
- Provider-visible control delivery does not become an alternative authority for
  canonical mailbox admission, Session wake, or Agent execution after a selection or
  settings mutation commits.
- Conversation-location selection and settings mutations are idempotent under
  duplicate callbacks and concurrent authorized actions.

## Open Assumptions

- Exact command names, labels, modal layouts, and context-menu terminology may differ
  between Slack and Discord while preserving the same user-visible capabilities.
- A provider may expose Slash Command, binding button, and message-context entry points
  simultaneously.
- Existing Azents Web administrative response-mode controls remain available but are
  not the primary workflow for provider participants.

## Confirmation

Confirmed by the requester on 2026-08-01 before ADR and design decisions began.
The requester amended and reconfirmed the Multi App channel-cardinality contract on
2026-08-01 before the Design was created.
