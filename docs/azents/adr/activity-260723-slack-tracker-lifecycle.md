---
title: "Slack Activity Tracker Lifecycle"
created: 2026-07-23
tags: [slack, external-channel, activity, delivery, architecture]
document_role: primary
document_type: adr
snapshot_id: activity-260723
---

# Slack Activity Tracker Lifecycle

- Snapshot: `activity-260723`
- Requirements: [`activity-260723/REQ`](../requirements/activity-260723-slack-tracker-lifecycle.md)

## Context

The implemented Activity Tracker combined Session navigation, progress, and retained
completion state. Later requester feedback requires transient activity, a separate
one-time Session link, and Slack-native read-only task presentation whose circular
indicator appears only for processing and in-progress Todo state.

## Decisions

### activity-260723/ADR-D1. Render independent native task cards

**Affects:** `activity-260723/REQ-2`

Render one status `task_card` followed by ordered Todo `task_card` blocks. Give the
status card and in-progress Todos `status: in_progress`, omit the optional status for
pending Todos, and use `status: complete` for completed Todos. Reuse canonical Channel
Work task IDs as Slack task IDs. Limit updates to 49 Todos so the status card and all
Todo cards fit Slack's 50-block message limit.

**Rejected:** A `plan` block requires an additional title and does not place the
processing indicator directly on the requested status message. Markdown, rich-text
emoji, checkboxes, and radio buttons either imitate native state or introduce unsafe
interaction semantics.

### activity-260723/ADR-D2. Bind one Session-link intent to initial activation

**Affects:** `activity-260723/REQ-1`

Create one button-only control-message intent keyed by the binding's initial
activation. Keep Session navigation outside the work-cycle desired payload and
Activity Tracker provider identity.

**Rejected:** Keeping the button in every Tracker conflates durable navigation with
transient operational state. Publishing the link for every invocation creates noisy
duplicate navigation messages.

### activity-260723/ADR-D3. Delete only after delivered final reply and reconcile both races

**Affects:** `activity-260723/REQ-3`, `activity-260723/REQ-4`

Commit the final reply and Tracker-delete intents before provider calls, attempt the
reply first, and permit deletion only after a durable delivered reply. Recovery
creates replacement Trackers only for active work with desired state. The reply and
Tracker-create completion paths both idempotently ensure cleanup, so either ordering
converges on one delete intent. A missing delete target is recorded as already absent.

**Rejected:** Retaining `Answer complete` contradicts the transient Tracker contract.
Deleting before reply confirmation can remove the only visible progress state when
the final answer fails. Recreating from finished desired state can leave a stale
Tracker after work has ended.
