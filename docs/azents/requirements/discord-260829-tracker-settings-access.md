---
title: "Discord Activity Tracker Conversation Settings Access Requirements"
created: 2026-08-29
updated: 2026-08-29
implemented: 2026-08-29
tags: [discord, external-channel, activity-tracker, settings]
document_role: primary
document_type: requirements
snapshot_id: discord-260829
---

# Discord Activity Tracker Conversation Settings Access Requirements

- Snapshot: `discord-260829`
- Document reference: `discord-260829/REQ`

## Problem

An eligible Discord mention in an already connected conversation can produce a separate Conversation settings message in addition to the Activity Tracker. This intermittently adds a redundant control message to the conversation while the Tracker remains the primary visible status surface.

## Primary Actor

A Discord participant invoking an Agent in an already connected conversation.

## Primary Scenario

The participant explicitly invokes the Agent in an existing Discord Binding. The resulting visible Activity Tracker gives the participant both Session navigation and Conversation settings access, and Discord does not post a separate settings-only message for that invocation.

## Supporting Scenarios

- An ordinary all-messages Discord input whose work remains Tracker-hidden does not create a Tracker or a settings-only message.
- A later explicit invocation that promotes hidden active work to a visible Tracker exposes both actions on that Tracker.
- Existing Slack Conversation settings presentation and Scheduled Task Tracker presentation remain unchanged.

## Goals

- Make the visible Discord Activity Tracker the recurring settings entry point for connected conversations.
- Remove the redundant Discord settings-only message produced by eligible follow-up invocations.
- Preserve the existing Conversation settings interaction, authorization, and current-state validation behavior.

## Non-Goals

- Changing Discord setup-location controls or application/message commands.
- Removing Conversation settings from the initial joined-presence control.
- Changing Slack settings controls or Slack Activity Trackers.
- Adding Conversation settings to Scheduled Task Trackers.
- Making Tracker-hidden Discord work visible solely to expose settings.

## Requirements

### REQ-1. Combined Discord Tracker actions

Every visible conversational Discord Activity Tracker must expose both View session and Conversation settings actions.

**Acceptance criteria**

- Initial and updated visible conversational Trackers show both actions in one action row.
- View session continues to open the current canonical Session.
- Conversation settings opens the existing settings experience for the exact connected Binding.

### REQ-2. No follow-up settings-only Discord message

An eligible explicit invocation in an existing Discord Binding must not create a separate settings-only provider message.

**Acceptance criteria**

- The invocation still creates or updates its eligible visible Activity Tracker.
- Discord provider evidence contains no additional Conversation settings-only message for the invocation.
- The absence of the settings-only message does not gate mailbox admission, Session wake-up, or Agent execution.

### REQ-3. Preserve settings authorization

Tracker-based Conversation settings access must retain the existing signed Binding scope and current-state authorization behavior.

**Acceptance criteria**

- A valid current control opens settings only for its bound connected conversation.
- Invalid, stale, disconnected, or unauthorized controls continue to return the existing bounded unavailable or rejected behavior.
- No new persistent settings authority or provider credential surface is introduced.

### REQ-4. Preserve unaffected presentation paths

The change must preserve unaffected provider and work-mode presentation behavior.

**Acceptance criteria**

- Tracker-hidden Discord work creates neither a Tracker nor a replacement settings message.
- Initial Discord joined presence retains its current actions.
- Slack settings controls and Activity Trackers remain unchanged.
- Scheduled Task Trackers remain unchanged.

## Fixed Constraints

- Discord component IDs must remain within provider limits and use the existing signed settings scope.
- Tracker create and update paths must present the same action set.
- Existing Binding, Work, and provider-projection ownership remain authoritative.
- The feature introduces no database migration, compatibility fallback, or new configuration.

## Open Assumptions

- The initial joined-presence settings action remains useful as the one-time connection control, while the Activity Tracker becomes the recurring invocation-time entry point.

## Confirmation

Confirmed by the requester on 2026-08-29 through the original implementation
direction and the explicit instruction to proceed without further intermediate
approval stops.
