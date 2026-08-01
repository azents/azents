---
title: "External Channel Binding Response Modes Requirements"
created: 2026-08-01
updated: 2026-08-01
implemented: 2026-08-01
tags: [external-channel, agent, session]
document_role: primary
document_type: requirements
snapshot_id: channel-260801
---

# External Channel Binding Response Modes Requirements

- Snapshot: `channel-260801`
- Document reference: `channel-260801/REQ`

## Problem

An Agent administrator cannot choose whether an already connected External Channel
binding responds only to explicit mentions or to every eligible message in the bound
conversation. The administrator also cannot define which behavior newly created
bindings should receive by default.

The missing controls prevent administrators from matching each connected conversation's
expected participation style while retaining the current authorization, context, and
execution behavior.

## Primary Actor

An Agent administrator.

## Primary Scenario

The Agent administrator selects the default response mode for future External Channel
bindings in Agent Settings. The administrator later opens Session Channels for a
connected Slack or Discord binding, sees that binding's concrete response mode, and
changes it when the conversation needs a different participation style. After the
change is saved, future eligible messages follow the new mode without altering past or
already-running work.

## Supporting Scenarios

- A new Slack or Discord binding receives the Agent default that is effective when the
  binding is created and retains that concrete mode if the Agent default changes later.
- Each existing binding retains the current all-eligible-message continuation behavior
  until an administrator explicitly selects another mode.
- An administrator can switch a connected binding between mention-gated and
  all-eligible-message participation without disconnecting or recreating it.

## Goals

- Let Agent administrators configure a default response mode for newly created
  External Channel bindings.
- Let Agent administrators view and change the response mode of each connected binding.
- Support consistent behavior for Slack and Discord bindings.
- Preserve existing behavior and authorization boundaries unless an administrator
  explicitly changes a binding's mode.

## Non-Goals

- Response-mode configuration at the connection, route, or Multi App channel-default
  level.
- Bulk mutation or automatic propagation to existing bindings when an Agent default
  changes.
- Editing the response mode of a disconnected historical binding.
- Participant-specific, schedule-specific, or message-type-specific filters, or
  response modes beyond `mention_only` and `all_messages`.
- Changing the mention or shortcut requirements that start a conversation before a
  binding exists.
- Changing existing grant, block, human-author eligibility, provider-history range,
  conversation-position, input admission, execution wake-up, or response-delivery
  behavior.
- Cancelling work in progress or retroactively processing past messages because a mode
  changed.

## Requirements

### REQ-1. Agent default response mode

An Agent administrator must be able to view and change the Agent's default response
mode for newly created External Channel bindings.

**Acceptance criteria**

- Agent Settings shows exactly `mention_only` and `all_messages` as available default
  modes.
- The saved default remains visible after the management surface is reloaded.
- An Agent that has never configured the setting uses `all_messages`.
- Existing Agents receive `all_messages` as their initial default.

### REQ-2. Creation-time binding mode

Every new External Channel binding must store a concrete response mode copied from the
Agent default that is effective when the binding is created.

**Acceptance criteria**

- A new Slack or Discord binding reports the same mode as the Agent default at its
  creation time.
- Changing the Agent default later does not change any existing binding.
- A binding never exposes an inherited or unresolved default state.

### REQ-3. Connected binding management

An Agent administrator must be able to view and change the concrete response mode of
each connected binding from Session Channels.

**Acceptance criteria**

- Session Channels displays the current mode for every connected binding.
- Saving a supported mode updates that binding without disconnecting or recreating it.
- The saved mode remains visible after the management surface is reloaded.
- A disconnected historical binding remains readable but its mode cannot be changed.

### REQ-4. Mention-only behavior

In `mention_only` mode, ordinary non-mention messages in the bound conversation must
not independently cause the Agent to execute or respond.

**Acceptance criteria**

- An eligible mention continues through the normal bound-Session execution and response
  flow.
- An ordinary non-mention message creates no independent Agent execution or response.
- A later eligible mention can include earlier visible non-trigger messages through the
  existing bounded conversation-history behavior.
- Existing explicit invocation behavior outside ordinary non-mention messages remains
  unchanged.

### REQ-5. All-messages behavior

In `all_messages` mode, every new message from a human who is eligible under the
current invocation policy must invoke the Agent for the same bound Session without
requiring a mention.

**Acceptance criteria**

- Each eligible new human-authored message follows the normal bound-Session execution
  and response flow.
- The mode does not make a blocked, unauthorized, bot, app, or system author eligible
  to invoke the Agent.
- Provider messages excluded by the current loop-prevention rules remain excluded.

### REQ-6. Compatibility for existing data

Introducing response modes must preserve the current invocation behavior of existing
Agents and bindings.

**Acceptance criteria**

- Existing Agents begin with the default `all_messages`.
- Existing connected and disconnected binding records have the concrete mode
  `all_messages`, reflecting their behavior while connected before the migration.
- Deployment alone does not cause an existing connected conversation to stop responding
  to eligible ordinary messages.
- A binding created after deployment retains the same default continuation behavior
  unless an administrator explicitly changes the Agent default.

### REQ-7. Effect of a binding-mode change

A saved binding-mode change must affect future message handling without rewriting past
or already-started work.

**Acceptance criteria**

- Messages processed after the mode change is saved use the new mode.
- Past non-trigger messages are not retroactively turned into independent invocations.
- Already accepted, queued, or running work is neither cancelled nor reclassified.
- Work that began under `all_messages` can finish normally after the binding changes to
  `mention_only`.

### REQ-8. Existing policy and lifecycle preservation

Both response modes must continue to obey the current External Channel authorization,
author eligibility, connectedness, Agent lifecycle, context, execution, and delivery
rules.

**Acceptance criteria**

- Existing grants, blocks, and automatic human-access settings retain their current
  precedence and effect.
- Bot, app, and system messages remain context-only.
- A disconnected binding cannot invoke the Agent in either mode.
- Provider-control delivery success or failure does not become a prerequisite for
  accepted Agent execution.

## Fixed Constraints

- The capability applies to connected Slack and Discord bindings.
- Only `mention_only` and `all_messages` are supported.
- The Agent default is copied at binding creation; existing bindings do not inherit
  later default changes.
- Existing and newly created Agents default to `all_messages`.
- Existing binding rows start as `all_messages`.
- Non-trigger messages continue to use the existing bounded provider-history and
  conversation-position behavior.
- The capability must not weaken current authorization, author-class, connection,
  lifecycle, loop-prevention, or execution/delivery independence guarantees.

## Open Assumptions

- None at reconfirmation time.

## Confirmation

Confirmed by the requester on 2026-08-01 after correcting the existing-binding
compatibility requirement during system-grounded analysis.
