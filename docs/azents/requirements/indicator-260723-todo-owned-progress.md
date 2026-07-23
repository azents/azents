---
title: "Todo-Owned Slack Activity Indicator Requirements"
created: 2026-07-23
tags: [slack, external-channel, activity, delivery]
document_role: primary
document_type: requirements
snapshot_id: indicator-260723
---

# Todo-Owned Slack Activity Indicator Requirements

- Snapshot: `indicator-260723`
- Document reference: `indicator-260723/REQ`

## Problem

When the Activity Tracker contains Todo cards, showing the same circular progress
indicator on both `Agent is working` and the active Todo duplicates the visual state,
especially on Slack mobile.

## Primary Actor

A Slack participant monitoring an Azents Agent with active Channel Work Todos.

## Primary Scenario

The participant sees `Agent is working` as context and one circular progress indicator
on the Todo that currently owns the work.

## Goals

- Keep one clear progress owner while Todo cards are present.
- Preserve visible processing feedback before the Agent has published any Todo.

## Non-Goals

- Removing the `Agent is working` context card.
- Changing pending or completed Todo presentation.
- Adding interactive Slack controls.

## Requirements

### REQ-1. Give Todo cards ownership of the active indicator

The summary card must not duplicate a Todo progress indicator.

**Acceptance criteria**

- A Tracker with no Todo cards shows the summary card with Slack's `in_progress`
  indicator.
- A Tracker with one or more Todo cards renders the summary card without status
  chrome.
- An in-progress Todo keeps Slack's `in_progress` indicator.
- A pending Todo omits status, and a completed Todo uses Slack's completed
  presentation.
- The rule is identical for live rendering and persisted-state recovery.

## Fixed Constraints

- The Tracker remains read-only and uses Slack `task_card` blocks.
- Existing provider delivery and work-cycle lifecycle behavior does not change.

## Requester Confirmation

The requester confirmed on 2026-07-23 that `Agent is working` does not need a circular
indicator when Todo items are present.
