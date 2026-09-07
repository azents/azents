---
title: "Discord Task-Only Tracker Edit Decisions"
created: 2026-09-07
tags: [discord, external-channel, activity-tracker, architecture]
document_role: primary
document_type: adr
snapshot_id: tracker-260907
---

# tracker-260907/ADR: Discord Task-Only Tracker Edit Decisions

- Snapshot: `tracker-260907`
- Document reference: `tracker-260907/ADR`
- Requirements:
  [`tracker-260907/REQ`](../requirements/tracker-260907-task-only-edit.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The implemented `discord-260907` policy uses any ordered task snapshot difference as
the Discord Tracker relocation trigger. This includes task-only Actions, which delete
or detach the current host and create a new silent standalone message despite no new
conversation message.

## Fixed and Derived Outcomes

- The Action transition already knows whether a conversational message is present.
- The existing create-or-update planner preserves standalone and reply-host semantics.
- A missing projection already creates a notification-suppressed standalone Tracker.
- Message-associated task changes keep the current reply-first, remove-before-create
  effect order.
- Failure, recovery, same-Binding serialization, and desired-revision fencing remain
  unchanged.

## Decisions

### tracker-260907/ADR-D1. Require both a task change and a message for relocation

**Affects:** `tracker-260907/REQ-1`, `REQ-2`, `REQ-3`

Discord enters the remove-before-create relocation path only when an explicitly
supplied ordered task snapshot differs from canonical tasks and the same Action
contains a conversational message. A task change without a message uses the existing
in-place create-or-update planner.

This keeps Tracker movement tied to a new conversational position without introducing
state, counters, thresholds, or provider history. A missing Tracker remains a recovery
case and is created directly because no existing host can be edited.

## Consequences

- Task status, details, output, source, identity, title, or order changes do not move an
  existing Tracker unless the Action also sends a message.
- Message-associated task changes continue to recreate one silent standalone Tracker.
- Existing reply-host Trackers may remain reply-hosted through task-only changes and
  converge to standalone on a later message-associated task change.
- No persisted state or migration changes.
