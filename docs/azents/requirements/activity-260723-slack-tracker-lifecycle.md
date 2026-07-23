---
title: "Slack Activity Tracker Lifecycle Requirements"
created: 2026-07-23
updated: 2026-07-23
tags: [slack, external-channel, activity, delivery]
document_role: primary
document_type: requirements
snapshot_id: activity-260723
---

# Slack Activity Tracker Lifecycle Requirements

- Snapshot: `activity-260723`
- Document reference: `activity-260723/REQ`

## Problem

The Slack Activity Tracker currently mixes progress, Session navigation, and terminal
answer state in one message. Simulated text lists do not provide the requested native
Slack task presentation, and retaining a completed Tracker leaves operational state in
the conversation after the final answer is already visible.

## Primary Actor

A Slack participant observing an Azents Agent work on an authorized thread request.

## Primary Scenario

When a Slack thread is first linked to a Session, the participant receives one compact
Session navigation message. Each later work cycle immediately creates a separate
Activity Tracker, updates that same message while the Agent works, and removes it only
after the final answer is confirmed delivered.

## Supporting Scenarios

- The participant distinguishes current, pending, and completed Channel Work tasks on
  Slack desktop or mobile.
- An administrator can inspect durable delivery state after a failed or ambiguous
  final answer or Tracker mutation.
- Active work recovers when the participant externally removes its Tracker message.

## Goals

- Keep Session navigation separate from transient Agent activity.
- Present Channel Work with Slack-native, read-only task UI.
- Make final Tracker deletion conditional on confirmed final-answer delivery.
- Reconcile external deletion and delivery races without recreating finished work.

## Non-Goals

- Allowing Slack users to edit Channel Work by interacting with the Tracker.
- Retaining an `Answer complete` Activity Tracker after the final answer.
- Using ordinary Session Todo state as the Channel Work source of truth.
- Automatically retrying ambiguous Slack mutations.

## Requirements

### REQ-1. Separate Session navigation from activity

The initial binding activation must publish Session navigation separately from every
Activity Tracker work cycle.

**Acceptance criteria**

- Initial binding activation creates one button-only message that opens the linked
  Azents Session.
- Repeated invocations on the same active binding do not create another Session-link
  message.
- Each new work cycle creates its Activity Tracker before Session execution wakes.
- The Activity Tracker has no separate heading and contains no Session link.

### REQ-2. Native read-only task presentation

The Tracker must use Slack-native task presentation rather than Markdown, rich-text
symbols, checkboxes, or radio buttons that imply editable state.

**Acceptance criteria**

- The current Agent processing message is shown with Slack's in-progress indicator.
- An in-progress Todo shows the in-progress circular indicator.
- A pending Todo has no status indicator.
- A completed Todo uses Slack's completed presentation.
- Task titles remain literal provider-safe text and task ordering is preserved.
- The presentation requires no Slack interaction callback.

### REQ-3. One transient Tracker per work cycle

All progress changes for one work cycle must mutate one provider message, and normal
completion must remove it.

**Acceptance criteria**

- Checking and task changes update the same retained Tracker identity.
- `finish` attempts the final conversational reply before Tracker deletion.
- Only a confirmed delivered final reply permits Tracker deletion.
- A failed, unknown, or not-attempted final reply leaves the Tracker available for
  inspection.
- A later work cycle creates a new Tracker identity.

### REQ-4. Convergent deletion and recovery

Tracker recovery must preserve active work without recreating finished work.

**Acceptance criteria**

- Confirmed external deletion or `message_not_found` during an active update creates
  at most one replacement from current desired state.
- Finished work never recreates a Tracker.
- `message_not_found` while deleting a finished Tracker is reconciled as already
  absent.
- If Tracker creation and final-reply delivery complete in either order, the later
  completion creates at most one pending delete intent when cleanup is required.

## Fixed Constraints

- Slack messages allow at most 50 Block Kit blocks; one processing card reserves one
  block, so a Channel Work update may contain at most 49 Todo items.
- Provider mutations retain the existing commit-before-call and at-most-once delivery
  contract.
- Slack callback transport remains HTTPS `POST /external-channel/v1/slack/events` or
  the existing Socket Mode path.

## Open Assumptions

- Slack accepts a `task_card` with omitted optional `status` and renders no status
  indicator for that card. This must be verified against the provider before the
  snapshot is marked implemented.

## Requester Confirmation

The requester confirmed the product behavior through sequential directives on
2026-07-23: remove the Tracker heading, delete the Tracker after successful work,
separate the one-time Session-link button, use real Slack task UI, show processing
with a circular indicator, and reserve Todo circular indicators for in-progress
items only.
