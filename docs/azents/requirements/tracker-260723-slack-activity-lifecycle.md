---
title: "Slack Activity Tracker Lifecycle Requirements"
created: 2026-07-23
updated: 2026-07-23
tags: [slack, external-channel, agent, delivery]
document_role: primary
document_type: requirements
snapshot_id: tracker-260723
---

# Slack Activity Tracker Lifecycle Requirements

- Snapshot: `tracker-260723`
- Document reference: `tracker-260723/REQ`
- Extends: [`slackops-260723/REQ`](slackops-260723-channel-control-feedback.md)

## Problem

The existing Slack progress projection does not acknowledge an idle invocation until
the Agent chooses to publish task progress, and normal completion removes the
operational message. Slack participants therefore cannot reliably see that work
started, follow one stable message through the complete work cycle, or retain a
completion result. An externally deleted Tracker can also leave later progress
invisible.

## Primary Actor

A Slack participant invoking an authorized Azents Agent in a bound thread.

## Primary Scenario

A participant sends the first eligible message while the binding has no unanswered
work. Slack immediately shows one Activity Tracker linked to the Azents Session. The
same message reflects later task changes and remains in the thread as completed after
the final answer is delivered.

## Supporting Scenarios

- A work cycle has no explicit tasks but still needs immediate acknowledgement.
- Slack or an administrator deletes the Tracker while the work cycle still exists.
- Final-answer delivery fails or has an unknown outcome.
- Session Channels displays the current work cycle and its actual provider state.

## Goals

- Acknowledge every new work cycle before Agent-controlled progress publication.
- Keep one stable Activity Tracker identity throughout a work cycle.
- Retain accurate completion feedback in Slack.
- Recover from confirmed external Tracker deletion without duplicating messages.

## Non-Goals

- Relaying ordinary assistant output to Slack without an explicit Channel Action.
- Retrying ambiguous provider mutations.
- Reusing one Tracker across separate work cycles.
- Changing Session Todo into the Channel Work source of truth.
- Keeping Trackers after binding or Session lifecycle cleanup.

## Requirements

### REQ-1. Immediate work-cycle acknowledgement

The first eligible invocation received while a binding has no unanswered work must
create an Activity Tracker before Agent execution begins.

**Acceptance criteria**

- Tracker creation does not depend on a Todo or Channel Action.
- The initial state communicates that the Agent is checking the message.
- Every Tracker contains a control that opens the bound Azents Session.
- A work cycle without tasks still retains its Tracker.

### REQ-2. One Tracker per work cycle

Acknowledgement, ordered task progress, and completion must use the same Slack
message for one work cycle.

**Acceptance criteria**

- Task creation and task-state changes update the retained Tracker.
- Updates do not post additional progress messages.
- A later work cycle creates a new Tracker rather than reusing a completed cycle's
  message.

### REQ-3. Delivered-answer completion

Normal completion must retain the Tracker and show completion only after the final
reply is confirmed delivered.

**Acceptance criteria**

- `finish` requires a final conversational reply.
- The completion update is attempted after the final-reply attempt.
- A failed, unknown, or not-attempted final reply prevents the completion update.
- Completed presentation removes active task content and retains the Session link.
- Normal completion does not delete the Tracker.

### REQ-4. Confirmed-deletion recovery

Azents must recreate a retained Tracker when Slack confirms that its provider message
no longer exists.

**Acceptance criteria**

- A matching Slack deletion event clears only the matching retained identity.
- A confirmed `message_not_found` update result has the same recovery behavior.
- Recovery creates at most one replacement for the confirmed deletion outcome.
- The replacement reflects the latest durable work-cycle state even when work
  changes while the replacement is being created.
- Ambiguous provider outcomes are not retried or treated as confirmed deletion.

### REQ-5. Accurate management projection

Session Channels must derive Activity Tracker status from the current work cycle and
its durable provider operations.

**Acceptance criteria**

- Previous work-cycle deliveries cannot classify the current work cycle.
- Ordered tasks remain canonical even when provider projection is missing, stale,
  failed, or unknown.
- Lifecycle cleanup failures remain inspectable without restoring terminal state.

## Fixed Constraints

- Provider mutation attempts remain durable and at most once.
- Credentials and secrets never enter Tracker payloads, prompts, UI state, logs, or
  test evidence.
- Binding disconnect, connection disconnect, Session archive, and decommission may
  delete retained Trackers after committing terminal local state.
- Approval control messages remain independent from the Activity Tracker lifecycle.

## Open Assumptions

- Slack deletion events and `message_not_found` are authoritative confirmation that
  a specific provider message identity no longer exists.

## Confirmation

Confirmed by the requester through the accumulated feedback and explicit instruction
to prioritize immediate Activity Tracker creation and recreate externally deleted
Trackers on 2026-07-23.
