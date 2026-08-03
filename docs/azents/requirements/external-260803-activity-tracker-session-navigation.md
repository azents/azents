---
title: "External Channel Activity Tracker Session Navigation Requirements"
created: 2026-08-03
updated: 2026-08-03
implemented: 2026-08-03
tags: [external-channel, slack, discord, session]
document_role: primary
document_type: requirements
snapshot_id: external-260803
---

# External Channel Activity Tracker Session Navigation Requirements

- Snapshot: `external-260803`
- Document reference: `external-260803/REQ`

## Problem

Slack and Discord users can see an Activity Tracker while an Agent is working, but the Tracker itself does not provide a direct way to open the associated Azents Session. Users must find a separate presence message or navigate through Azents manually.

## Primary Actor

A Slack or Discord participant viewing an Agent's current Activity Tracker.

## Primary Scenario

A participant views an Activity Tracker in Slack or Discord, selects its Session navigation control, and arrives at the Azents Session associated with that Tracker.

## Supporting Scenarios

- The participant can use the same navigation control while the Tracker is initially checking the message.
- The navigation control remains available after the Tracker is updated with active work details.

## Goals

- Make the associated Azents Session directly reachable from every visible Slack and Discord Activity Tracker state.
- Keep Session navigation consistent with the existing External Channel Session navigation experience.

## Non-Goals

- Changing Session access authorization or granting access through the Tracker.
- Changing Activity Tracker creation, update, completion, deletion, or retention behavior.
- Adding a separate provider message solely for Session navigation.
- Changing existing joined, left, setup, or conversation-settings controls.

## Requirements

### REQ-1. Activity Tracker Session navigation

Every visible Slack and Discord Activity Tracker must provide a clearly labeled control that navigates to the Azents Session associated with that Tracker.

**Acceptance criteria**

- A newly created Slack Activity Tracker provides a `View session` control.
- A newly created Discord Activity Tracker provides a `View session` control.
- Selecting the control opens the canonical Azents Agent Session represented by the Tracker.

### REQ-2. Navigation continuity across Tracker updates

Session navigation must remain available as the Activity Tracker changes from its initial checking state to later work states.

**Acceptance criteria**

- Updating a Slack Activity Tracker preserves its `View session` control.
- Updating a Discord Activity Tracker preserves its `View session` control.
- The control continues to target the same associated Session after each update.

### REQ-3. Existing lifecycle and authorization preservation

Adding Session navigation must not change the Activity Tracker lifecycle or Session access rules.

**Acceptance criteria**

- Tracker creation, update, completion, and deletion behavior remains unchanged apart from the navigation control.
- Opening the target Session remains subject to the existing Azents Web authorization behavior.
- No additional provider message is created solely to expose the navigation control.

## Fixed Constraints

- Slack and Discord must use the same user-visible `View session` label already used by External Channel Session navigation.
- The destination must be the existing canonical Azents Agent Session route for the Tracker's associated Workspace, Agent, and Session.
- Provider delivery remains best-effort and must not gate mailbox admission, Session wake-up, or Agent execution.
- Verification must use unit/provider-fake or public-boundary tests without mutating product data directly.

## Open Assumptions

- None.

## Confirmation

Confirmed by the requester on 2026-08-03 before ADR and design decisions began.
