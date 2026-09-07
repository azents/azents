---
title: "Silent Discord Scheduled Task Tracker Decisions"
created: 2026-09-07
tags: [discord, scheduled-task, external-channel, activity-tracker, architecture]
document_role: primary
document_type: adr
snapshot_id: scheduled-260907
---

# scheduled-260907/ADR: Silent Discord Scheduled Task Tracker Decisions

- Snapshot: `scheduled-260907`
- Document reference: `scheduled-260907/ADR`
- Requirements:
  [`scheduled-260907/REQ`](../requirements/scheduled-260907-silent-discord-tracker.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The Discord delivery boundary already suppresses notifications for conversational
`PROGRESS_CREATE` Tracker messages but explicitly excludes
`tracker_kind=scheduled_task`. Scheduled Task registration and deletion notices use
`CONTROL_MESSAGE`, while replies and terminal results use their existing reply paths.

## Fixed and Derived Outcomes

- Removing the Scheduled Task exception affects Tracker-host creation without changing
  registration, deletion, progress-reply, or terminal-result messages.
- Existing Tracker updates remain provider edits and need no notification option.
- The public Discord SDK flag path, provider authority, and one-attempt effect contract
  remain unchanged.

## Decisions

### scheduled-260907/ADR-D1. Suppress every Discord progress-host creation

**Affects:** `scheduled-260907/REQ-1`, `REQ-2`, `REQ-3`

Every Discord `PROGRESS_CREATE` operation requests notification suppression,
independent of whether the Tracker belongs to conversational Channel Work or a
Scheduled Task cycle. Provider operation kind, rather than Tracker ownership, defines
the silent-message boundary.

The existing Scheduled Task exception is removed. Other Scheduled Task publications
remain outside this boundary because they are not `PROGRESS_CREATE` operations.

## Consequences

- Initial and recovery Scheduled Task Tracker messages become silent.
- Conversational Tracker creation remains silent.
- Scheduled Task registration, deletion, progress replies, and terminal results remain
  notification-bearing according to their current delivery contracts.
- No data migration or compatibility path is required.
