---
title: "Discord Moving Activity Tracker Requirements"
created: 2026-09-05
updated: 2026-09-05
implemented: 2026-09-05
tags: [discord, external-channel, activity-tracker, channel-work]
document_role: primary
document_type: requirements
snapshot_id: discord-260905
---

# Discord Moving Activity Tracker Requirements

- Snapshot: `discord-260905`
- Document reference: `discord-260905/REQ`

## Problem

A Discord conversational Activity Tracker remains at the provider position where it
was first created. During long-running Work, later conversation pushes the Tracker out
of view even though its content continues to update. Recreating the Tracker on every
update would add notification and visual noise, while temporarily showing multiple
Trackers makes the current status ambiguous.

## Primary Actor

A Discord participant monitoring long-running Agent Work in a connected conversation.

## Primary Scenario

The Agent sends a conversational progress message together with a changed Work title or
task list. Discord delivers the message normally, removes the previous Tracker, and
then presents the complete latest Tracker on the newly delivered message. The
participant sees at most one Tracker and finds it beside the latest meaningful progress
message.

## Supporting Scenarios

- The Agent changes Work state without sending a conversational message.
- The Agent sends a conversational message without changing Work state.
- Discord fails or ambiguously completes a Tracker-only provider mutation.
- The Work finishes while its Tracker is hosted by a conversational message.

## Goals

- Keep the Discord Tracker near meaningful Agent progress communication.
- Avoid additional notification-bearing messages solely to move the Tracker.
- Keep at most one visible Tracker during a normal move.
- Preserve canonical Work and conversational delivery when Tracker projection fails.

## Non-Goals

- Moving the Tracker on elapsed time, channel message count, or heartbeat updates.
- Providing exactly-once Tracker projection or durable provider retry work.
- Guaranteeing that a Tracker is continuously visible during a move or provider
  failure.
- Changing Slack or Scheduled Task Tracker presentation.
- Defining Discord client notification-preview behavior.

## Requirements

### REQ-1. Move the Tracker with meaningful progress messages

When a Discord conversational Action contains both a message and a changed Work title
or task list, the latest complete Tracker must move to the newly delivered message.

**Acceptance criteria**

- The conversational message is delivered before Tracker relocation begins.
- The previous Tracker is removed before the Tracker is attached to the new message.
- The normal successful path never shows two Trackers for one Work cycle.
- A temporary interval with no Tracker is allowed between removal and attachment.
- If the message is split into parts, the Tracker is attached to the final part only
  after every reply part is delivered.

### REQ-2. Preserve Tracker position when communication or state is unchanged

Discord Tracker movement must follow the semantic relationship between conversational
communication and Work-state change.

**Acceptance criteria**

- A state-only update edits the current Tracker in place.
- A state-only update creates one standalone, notification-suppressed Tracker when no
  current Tracker exists.
- A message-only Action sends the message without changing Tracker position or content.

### REQ-3. Treat Tracker delivery as a recoverable projection

Tracker provider failures must not roll back canonical Work or a successfully delivered
conversational message.

**Acceptance criteria**

- Failed or ambiguous previous-Tracker removal prevents attachment to the new message.
- A later progress update attempts to project the complete latest Work snapshot again.
- Failed attachment may leave the Work temporarily without a visible Tracker.
- Tracker failure does not fail or reverse the canonical title and ordered task update.
- No durable retry queue, duplicate-compensation workflow, or guarantee of continuous
  Tracker visibility is introduced.

### REQ-4. Preserve unaffected provider behavior

The change must remain specific to Discord conversational Work.

**Acceptance criteria**

- Slack conversational Trackers keep their retained standalone-message lifecycle.
- Scheduled Task Trackers remain standalone.
- Existing final-reply delivery gating remains authoritative before Tracker cleanup.
- Existing Session navigation and Conversation settings controls remain present on the
  current conversational Tracker.

## Fixed Constraints

- Canonical Channel Work remains the sole authority for title, tasks, lifecycle, and
  desired progress revision.
- Provider effects remain commit-before-call and immediate one-attempt operations.
- Tracker relocation must not create a second source of truth from Discord message
  content.
- The current Discord App identity may edit or delete only messages it owns.

## Open Assumptions

- Discord message edits do not create an additional notification; notification-preview
  details remain client behavior and require separate observation.

## Confirmation

Confirmed by the requester through the Discord design discussion on 2026-09-05. The
requester explicitly selected remove-before-attach behavior, temporary Tracker absence
over visible duplication, best-effort recovery on later progress updates, and then
requested implementation.
