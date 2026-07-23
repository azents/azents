---
title: "Todo-Owned Slack Activity Indicator"
created: 2026-07-23
tags: [slack, external-channel, activity, delivery, architecture]
document_role: primary
document_type: adr
snapshot_id: indicator-260723
---

# Todo-Owned Slack Activity Indicator

- Snapshot: `indicator-260723`
- Requirements: [`indicator-260723/REQ`](../requirements/indicator-260723-todo-owned-progress.md)

## Context

The Slack-native Activity Tracker currently gives the summary card and active Todo
card the same `in_progress` status. On mobile this renders two circular progress
indicators for one work state.

## Decisions

### indicator-260723/ADR-D1. Make summary status conditional on an empty Todo list

**Affects:** `indicator-260723/REQ-1`

Keep the summary `task_card` in every Tracker. Include `status: in_progress` only when
the ordered Todo list is empty. Once any Todo exists, omit the summary status and let
the in-progress Todo own the circular indicator.

**Rejected:** Removing the summary card loses the stable `Agent is working` context.
Keeping both indicators duplicates progress state, while moving every status into the
summary makes it impossible to identify the active Todo.
