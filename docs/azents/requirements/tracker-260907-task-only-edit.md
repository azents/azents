---
title: "Discord Task-Only Tracker Edit Requirements"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-07
tags: [discord, external-channel, activity-tracker, channel-work]
document_role: primary
document_type: requirements
snapshot_id: tracker-260907
---

# Discord Task-Only Tracker Edit Requirements

- Snapshot: `tracker-260907`
- Document reference: `tracker-260907/REQ`

## Problem

Recreating the Discord Activity Tracker for a task update that sends no conversational
message moves the Tracker without adding conversation context. This creates unnecessary
visual activity when an in-place Tracker edit can show the same latest state.

## Primary Actor

A Discord participant monitoring Agent work in a connected conversation.

## Primary Scenario

The Agent changes the ordered task snapshot without sending a conversational message.
Discord updates the current Tracker at its existing position. A later Action that
combines a changed task snapshot with a conversational message may relocate the Tracker
after that message.

## Supporting Scenarios

- No current Tracker exists when a task-only progress update occurs.
- The current Tracker is hosted on a standalone message or a conversational reply.
- A task-changing Action also sends a conversational message.
- Discord fails or ambiguously completes an in-place Tracker update.

## Goals

- Keep message-free task updates at the current Tracker position.
- Preserve task-change relocation when a conversational message gives the move context.
- Restore a missing Tracker without requiring a conversational message.
- Preserve existing projection failure and concurrency boundaries.

## Non-Goals

- Adding counters, timers, heartbeat-based movement, or provider-channel activity state.
- Changing silent standalone creation, remove-before-create ordering, or reply-host
  compatibility.
- Changing Slack or Scheduled Task Tracker behavior.
- Adding durable provider retries or exactly-once projection.

## Requirements

### REQ-1. Edit the current Tracker for task-only updates

A Discord progress Action that changes the ordered task snapshot without a
conversational message must retain the current Tracker host and position.

**Acceptance criteria**

- A standalone Tracker receives a complete in-place update.
- A reply-hosted Tracker receives a Tracker-only partial update that preserves
  conversational content.
- A missing Tracker is created as a notification-suppressed standalone message.
- The Action does not delete and recreate an existing Tracker.

### REQ-2. Keep message-associated task relocation

A Discord Action that contains both a conversational message and a changed ordered task
snapshot must retain the current remove-before-create relocation behavior.

**Acceptance criteria**

- Reply effects are attempted before Tracker relocation effects.
- An existing Tracker is removed or detached before standalone replacement creation.
- A missing Tracker is created directly as a notification-suppressed standalone
  message.
- Reply delivery does not gate task-change relocation.

### REQ-3. Preserve recovery and unaffected behavior

The changed trigger must preserve existing provider projection and isolation contracts.

**Acceptance criteria**

- Failed or ambiguous task-only edits remain best-effort and recover through a later
  complete progress projection.
- Same-Binding Action serialization and exact desired-revision revalidation remain.
- Slack and Scheduled Task Trackers are unchanged.
- No schema migration, counter, durable retry, or distributed lock is introduced.

## Fixed Constraints

- Canonical Channel Work remains the sole authority for tasks and desired progress.
- Provider effects remain commit-before-call immediate one-attempt operations.
- Existing `standalone | reply` host classification remains authoritative for update
  and cleanup behavior.

## Open Assumptions

- A message-free progress update has no user-visible conversation position that would
  justify relocating an existing Tracker.

## Confirmation

Confirmed by the requester on 2026-09-07. The requester explicitly required task
updates without a conversational message to edit the existing Tracker and requested a
separate follow-up PR.
