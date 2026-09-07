---
title: "Silent Discord Scheduled Task Tracker Requirements"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-07
tags: [discord, scheduled-task, external-channel, activity-tracker]
document_role: primary
document_type: requirements
snapshot_id: scheduled-260907
---

# Silent Discord Scheduled Task Tracker Requirements

- Snapshot: `scheduled-260907`
- Document reference: `scheduled-260907/REQ`

## Problem

Starting a Scheduled Task in a Discord-bound Session creates an Activity Tracker as a
normal message. The execution status should remain visible without generating an
additional notification solely because scheduled work started.

## Primary Actor

A Discord participant whose connected Session runs a Scheduled Task.

## Primary Scenario

A Scheduled Task cycle starts and creates its initial Discord Activity Tracker. The
Tracker appears in the bound conversation as a notification-suppressed message and
continues through the existing update and cleanup lifecycle.

## Supporting Scenarios

- A missing Scheduled Task Tracker is recreated during a later progress update.
- A Scheduled Task is registered or explicitly deleted in a bound conversation.
- The cycle publishes progress messages or a terminal result.

## Goals

- Suppress notifications for Discord Scheduled Task Tracker creation.
- Preserve the existing Tracker presentation, controls, update, and cleanup behavior.
- Keep registration, deletion, progress-message, and terminal-result delivery
  unchanged.

## Non-Goals

- Silencing Scheduled Task registration or deletion notices.
- Silencing conversational progress messages or terminal results.
- Changing Slack Scheduled Task presentation.
- Adding configuration, state, migration, retry, or replay behavior.

## Requirements

### REQ-1. Create Discord Scheduled Task Trackers silently

Every Discord message created solely to host a Scheduled Task Activity Tracker must
request provider notification suppression.

**Acceptance criteria**

- Initial Scheduled Task Tracker creation is notification-suppressed.
- Missing-host recovery creation is notification-suppressed.
- Tracker updates continue editing the existing message.
- Tracker Embed content and Session navigation controls are unchanged.

### REQ-2. Preserve other Scheduled Task publications

The notification change must apply only to Tracker-host message creation.

**Acceptance criteria**

- Discord Scheduled Task registration and deletion notices retain their existing
  notification behavior.
- Scheduled progress replies and terminal results retain their existing notification
  behavior.
- Slack Scheduled Task Trackers are unchanged.

### REQ-3. Preserve existing delivery guarantees

The change must retain current provider-effect authority and failure behavior.

**Acceptance criteria**

- Provider effects remain immediate one-attempt operations.
- Canonical Scheduled Task cycle state is unaffected by provider success or failure.
- No new schema, configuration, retry, or distributed coordination is introduced.

## Fixed Constraints

- Scheduled Task cycles keep their independent Tracker projection state.
- Discord notification suppression uses the existing provider SDK flag path.
- Provider credentials and exact Binding authority remain unchanged.

## Open Assumptions

- Supported Discord clients honor the notification-suppression flag for Tracker
  messages.

## Confirmation

Confirmed by the requester on 2026-09-07. The requester explicitly required the
Activity Tracker shown during Scheduled Task execution to use silent message delivery.
