---
title: "Discord Tracker Title-List Relocation Requirements"
created: 2026-10-07
implemented: 2026-10-07
tags: [discord, external-channel, activity-tracker]
document_role: primary
document_type: requirements
snapshot_id: tracker-261007
---

# Discord Tracker Title-List Relocation Requirements

- Snapshot: `tracker-261007`
- Document reference: `tracker-261007/REQ`

## Problem

Tracker movement currently depends on conversational message presence and changes to
any task field. Participants need movement to represent changes to the work list,
while completion and task comments remain visible in the retained Tracker.

## Primary Actor and Scenario

A Discord conversation participant observes an Agent's plan as work progresses.
A changed task-title list moves the Tracker to a new message; routine updates to
those tasks keep its current position.

## Goals and Non-Goals

- Make Tracker movement depend on task titles alone, independent of reply presence.
- Preserve current Slack, completion, notification, and failure behavior.
- Do not add settings, stored history, migrations, or automatic retries.

## Requirements

### REQ-1. Move for changes to the task-title list

A changed task title, added task, or removed task recreates the Discord Tracker,
including when no conversational reply accompanies the plan update.

**Acceptance criteria**

- Renaming one task, adding a task, or removing a task moves an existing Tracker.
- A plan-only update and an update with a reply use the same change criterion.

### REQ-2. Retain the Tracker for routine task updates

When task titles remain the same, update the existing Tracker in place.

**Acceptance criteria**

- Completing or reopening some tasks does not recreate the Tracker.
- Adding task comments or result information does not recreate the Tracker.
- Changes to IDs or sources without title changes do not recreate the Tracker.
- Changing only the overall activity title does not recreate the Tracker.

### REQ-3. Preserve unaffected lifecycle behavior

Keep existing removal-before-replacement safety, reply content preservation,
notification suppression, missing-host creation, final cleanup, and Slack behavior.

**Acceptance criteria**

- A replacement is created only after confirmed removal of an existing host.
- A reply-hosted Tracker is detached without deleting the conversational content.
- Replacement Trackers are notification-suppressed; reply delivery is independent.

## Fixed Constraints and Interpretation

- Compare title lists in their existing canonical order; reordering distinct titles
  changes the displayed list. This interpretation was disclosed in the initial
  implementation briefing.
- Existing validation and string normalization remain unchanged.

## Confirmation

The requester directly requested this bounded behavior change on 2026-10-07,
explicitly distinguishing completion/comment edits from title changes and additions
or removals. This document records that instruction without adding product scope.
