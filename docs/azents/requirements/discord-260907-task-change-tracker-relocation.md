---
title: "Discord Task-Change Tracker Relocation Requirements"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-07
tags: [discord, external-channel, activity-tracker, channel-work]
document_role: primary
document_type: requirements
snapshot_id: discord-260907
---

# Discord Task-Change Tracker Relocation Requirements

- Snapshot: `discord-260907`
- Document reference: `discord-260907/REQ`

## Problem

Moving the Discord Activity Tracker onto each conversational reply makes Tracker
attachment and removal visually noisy. A silent standalone Tracker does not create
notification noise, so its position should change only when the task list itself
changes.

## Primary Actor

A Discord participant monitoring Agent work in a connected conversation.

## Primary Scenario

The Agent publishes a conversational update with a changed ordered task list. Discord
delivers the conversation normally, removes the previous Tracker, and creates the
complete latest Tracker as a new notification-suppressed standalone message. When a
later update keeps the same task list, the Tracker remains at its current position.

## Supporting Scenarios

- The Agent changes tasks without sending a conversational message.
- The Agent changes only the Work title while retaining the same tasks.
- The current Tracker is hosted on a conversational reply created by the previous
  behavior.
- Discord fails or ambiguously completes Tracker removal or creation.

## Goals

- Relocate the Tracker only when the ordered task snapshot changes.
- Keep unchanged-task updates visually stable.
- Use silent standalone Tracker creation to avoid notification noise.
- Preserve canonical Work and conversational delivery when Tracker projection fails.

## Non-Goals

- Counting messages, progress updates, or elapsed time before relocation.
- Hosting newly relocated Trackers on conversational replies.
- Adding durable provider retries, exactly-once relocation, or compensation work.
- Changing Slack or Scheduled Task Tracker behavior.
- Guaranteeing continuous Tracker visibility through a provider failure.

## Requirements

### REQ-1. Relocate on an ordered task change

When a Discord Action replaces the ordered task snapshot with a different snapshot,
the current Tracker must be removed and the complete latest Tracker must be created as
a new notification-suppressed standalone message.

**Acceptance criteria**

- A difference in task identity, order, title, status, details, output, or sources
  counts as a task change.
- Supplying an identical task snapshot does not count as a task change.
- When the Action also sends a conversational reply, reply effects occur before
  Tracker relocation so the new standalone Tracker follows the reply.
- The previous Tracker is removed or detached before the replacement is created.
- A missing current Tracker requires only standalone creation.

### REQ-2. Preserve position when tasks are unchanged

An Action that does not change the ordered task snapshot must retain the current
Tracker host and position.

**Acceptance criteria**

- A title-only progress change updates the current Tracker in place.
- Supplying the same complete task snapshot updates the current Tracker in place.
- A message-only Action does not mutate or relocate the Tracker.
- A currently reply-hosted Tracker remains reply-hosted until a later task change or
  terminal cleanup.

### REQ-3. Keep relocation recoverable and best-effort

Tracker provider failures must not roll back canonical Work or a successfully
delivered conversational message.

**Acceptance criteria**

- Failed or ambiguous current-Tracker removal prevents replacement creation in the
  same Action.
- Failed or ambiguous replacement creation may leave the Tracker absent or uncertain.
- A later progress change attempts to project the complete latest Work snapshot using
  the current projection observation.
- No durable retry queue or duplicate-compensation workflow is introduced.

### REQ-4. Preserve unaffected behavior and concurrency boundaries

The change must remain specific to Discord conversational Activity Trackers.

**Acceptance criteria**

- Slack and Scheduled Task Trackers retain their existing standalone lifecycles.
- Existing final-reply delivery gating remains authoritative before terminal cleanup.
- Same-Binding Actions remain serialized within one service process.
- Exact desired-progress revision validation remains in place before Tracker provider
  I/O.

## Fixed Constraints

- Canonical Channel Work remains the sole authority for title, tasks, lifecycle, and
  desired progress revision.
- Provider effects remain commit-before-call immediate one-attempt operations.
- Existing reply-host projection state must remain readable and safely cleanable.
- The Discord App may edit or delete only messages it owns.

## Open Assumptions

- Discord notification suppression on standalone Tracker creation remains effective
  across supported clients.

## Confirmation

Confirmed by the requester on 2026-09-07. The requester explicitly selected task
snapshot changes as the sole relocation trigger, rejected counter-based relocation,
and required unchanged-task updates to retain the current Tracker position.
