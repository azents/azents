---
title: "Slack Channel Work Presence and Tracker Parity Requirements"
created: 2026-08-29
updated: 2026-08-29
implemented: 2026-08-29
tags: [slack, external-channel, activity-tracker, channel-work]
document_role: primary
document_type: requirements
snapshot_id: slack-260829
---

# Slack Channel Work Presence and Tracker Parity Requirements

- Snapshot: `slack-260829`
- Document reference: `slack-260829/REQ`

## Problem

Slack conversational Work currently shows an Activity Tracker for every accepted
message and has no provider-native execution-presence projection. This differs from
the completed Discord experience, where execution presence is independent of Tracker
visibility, ordinary all-messages Work may begin without Tracker chrome, and
unfinished Todo publication promotes that Work to one visible Tracker.

The Slack presentation also separates recurring conversation-settings access from the
visible conversational Tracker, creating an additional operational message after an
eligible invocation.

## Primary Actor

A Slack participant in a connected channel or thread conversation.

## Primary Scenario

The participant sends an ordinary message through an existing all-messages Binding.
Slack immediately shows that the Agent is working without publishing an initial
Activity Tracker. If the Agent later publishes unfinished Todos, Slack shows one
Tracker with the complete current plan and normal conversation actions. The final
reply is delivered at the currently configured channel or thread target, after which
the temporary Work presence and Tracker are cleaned up.

## Supporting Scenarios

- An explicit invocation shows both execution presence and an initial checking
  Tracker.
- A later explicit invocation promotes still-hidden active Work without creating a
  second Tracker.
- Slack channel and thread Bindings retain their existing Resource and Session
  mapping while using provider-appropriate presence presentation.
- Provider or process restart restores active execution presence from canonical Work.
- Visible conversational Trackers provide both Session navigation and conversation
  settings without a settings-only message.
- Slack message routing follows the completed Discord response-mode and exact-Binding
  semantics while retaining the provider-specific channel/thread mapping already
  defined by the current Spec.

## Goals

- Give Slack participants immediate provider-native feedback for every active
  conversational Work cycle.
- Match the completed Discord Tracker visibility, Todo promotion, identity, action,
  and cleanup lifecycle.
- Preserve the configured Slack channel or thread conversation experience exactly.
- Align Slack message-routing semantics with Discord wherever the current Spec does
  not require a provider-specific difference.
- Keep canonical Channel Work as the sole presence and Tracker authority.

## Non-Goals

- Changing Slack channel/thread selection, response mode, Resource identity, Binding
  ownership, Azents Session creation, or final-reply target.
- Adding Azents App Home ingress, direct-message handling, suggested prompts, native
  Stop, or model-output streaming behavior beyond the provider-owned surface exposed
  by required Slack Agent mode.
- Changing Discord, Scheduled Task, approval, file-delivery, joined-presence, or
  leave-presence behavior.
- Making provider presentation state a durable execution or delivery authority.

## Requirements

### REQ-1. Active Work has native Slack execution presence

Every active conversational Slack Work cycle must present provider-native execution
presence independently of whether an Activity Tracker is visible.

**Acceptance criteria**

- Presence begins for explicit invocations and ordinary all-messages inputs.
- Presence remains active for hidden and visible Work.
- Presence ends on finish, ignore, cancellation, Binding termination, or unavailable
  canonical Work.
- Restart or ownership handover restores presence for still-active Work.
- Presentation failure does not fail or mutate canonical Work or connection health.

### REQ-2. Tracker visibility matches the completed Discord experience

Slack conversational Tracker visibility and promotion must follow the same semantic
contract as Discord.

**Acceptance criteria**

- An explicit invocation starts with one visible checking Tracker.
- An ordinary input admitted by an existing all-messages Binding starts with no
  Tracker.
- Publishing a valid progress snapshot with unfinished Todos promotes hidden Work and
  creates one Tracker.
- A later eligible explicit invocation also promotes still-hidden active Work.
- Visibility is monotonic and one Work cycle never creates duplicate Tracker
  identities.

### REQ-3. Visible Trackers contain the complete plan and actions

A visible Slack conversational Tracker must render the current complete Work snapshot
and the same functional actions as the completed Discord Tracker.

**Acceptance criteria**

- Checking Work is presented as one accessible checking card.
- Planned Work is presented as one ordered plan with task statuses, details, output,
  and labeled sources.
- Updates replace the same Tracker with the latest complete snapshot.
- The Tracker provides `View session` and `Conversation settings`.
- Eligible invocations do not create a separate settings-only message.

### REQ-4. Completion and cleanup preserve canonical delivery ordering

Slack presence and Tracker cleanup must preserve the existing commit-before-provider
and final-reply ordering contracts.

**Acceptance criteria**

- Final reply effects are attempted before Tracker deletion.
- Only a delivered final reply permits Tracker deletion.
- Failed, unknown, or not-attempted replies leave Tracker deletion not attempted.
- Ignore sends no reply and cleans up the current presence and Tracker.
- A later Work cycle uses a new Tracker identity.

### REQ-5. Existing Slack conversation mapping remains unchanged

The feature must not change the user-visible or canonical relationship among Slack
channels, Slack threads, Resources, Bindings, Azents Sessions, and reply targets.

**Acceptance criteria**

- Parent-channel Bindings continue to deliver final replies to the parent channel.
- Thread Bindings continue to deliver final replies to the exact retained thread.
- Presence presentation does not create, split, merge, or retarget Azents Sessions.
- Existing response-mode, authorization, history, participation, and lifecycle
  behavior remains unchanged.

### REQ-6. Slack installation exposes the required Agent capability

Slack setup and validation must make Agent mode a required installation capability
for native thread Work presence.

**Acceptance criteria**

- Generated setup guidance declares the App as a Slack Agent.
- Validation requires the scopes added by that declaration and directs operators to
  update and reinstall an incomplete App.
- A runtime provider rejection because Agent functionality is unavailable does not
  silently fall back to a different thread-presence contract.
- Presence rejection does not roll back canonical Work, Tracker, or reply delivery.

### REQ-7. Message routing matches Discord semantics

Slack routing must use the same provider-neutral invocation, response-mode, Binding
precedence, and reply-target semantics as Discord unless the current Spec explicitly
defines a Slack-specific channel/thread representation.

**Acceptance criteria**

- Explicit provider invocation triggers both `mention_only` and `all_messages`
  Bindings.
- Ordinary human messages trigger only an existing `all_messages` Binding.
- An exact connected thread Binding resolves before parent-channel participation.
- Connected-App output and unsupported provider message mutations do not trigger
  Agent Work.
- Final replies remain at the exact configured Resource target.
- The existing Slack parent-channel fan-in and thread Resource representation remain
  unchanged.

## Fixed Constraints

- The completed Discord Work presence and Tracker lifecycle is the product-semantic
  source of truth.
- Slack channel and thread targets may use different provider APIs while exposing the
  same user-visible lifecycle.
- Slack Agent mode is a required installation prerequisite. Slack's provider-owned
  Agent surface and guest-access restrictions are accepted platform consequences, but
  they do not authorize Azents App Home or direct-message routing.
- Canonical Channel Work state remains the sole authority for active presence,
  Tracker visibility, desired progress, and cleanup eligibility.
- Provider effects retain bounded, authenticated, one-attempt mutation semantics
  unless presence reconciliation explicitly derives current active Work.
- Current Slack channel/thread Resource and Session mapping remains authoritative.

## Open Assumptions

- None.

## Confirmation

Confirmed by the requester on 2026-08-29 through the approved Slack policy and the
instruction to implement it, with the explicit constraint that channel and thread
targets may require different Slack APIs while preserving the existing mapping and
the completed Discord user experience.
