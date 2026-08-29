---
title: "Discord Todo Work Activity Tracker Visibility Requirements"
created: 2026-08-29
updated: 2026-08-29
implemented: 2026-08-29
tags: [discord, external-channel, activity-tracker, channel-work]
document_role: primary
document_type: requirements
snapshot_id: tracker-260829
---

# Discord Todo Work Activity Tracker Visibility Requirements

- Snapshot: `tracker-260829`
- Document reference: `tracker-260829/REQ`

## Problem

An ordinary message admitted by an existing Discord all-messages Binding starts a
Tracker-hidden Channel Work cycle. If the Agent later publishes an unfinished Todo
list, the Work and tasks remain canonical but the Activity Tracker stays hidden. The
participant therefore cannot see the active plan even though the Agent has explicitly
declared ongoing work.

## Primary Actor

A Discord participant in a connected all-messages conversation.

## Primary Scenario

The participant sends an ordinary message without mentioning the Agent. The Agent
starts Channel Work and publishes an unfinished Todo list. Discord then shows one
Activity Tracker containing the current plan and the conversation's normal Tracker
actions.

## Supporting Scenarios

- Ordinary Discord Work that remains in the initial checking state without a published
  Todo list may remain Tracker-hidden.
- A later explicit mention still promotes active hidden Work when no task-bearing
  update has promoted it yet.
- Later Todo changes update the same Tracker instead of creating another Tracker.
- Slack conversational Trackers and Scheduled Task Trackers remain unchanged.

## Goals

- Make an Agent-authored unfinished Todo list sufficient to show the conversational
  Discord Activity Tracker.
- Preserve one Tracker identity throughout the Work cycle.
- Keep initial non-mention checking work lightweight until the Agent declares a plan.

## Non-Goals

- Showing a Tracker for every ordinary Discord message before the Agent publishes
  unfinished tasks.
- Changing Discord typing, reply, settings authorization, joined presence, or final
  cleanup contracts.
- Changing Slack or Scheduled Task presentation.
- Adding configuration, persistence schema, or compatibility modes.

## Requirements

### REQ-1. Unfinished Todo publication shows the Tracker

A Tracker-hidden Discord Work cycle must become Tracker-visible when the Agent
publishes a valid progress update containing at least one unfinished Todo.

**Acceptance criteria**

- The task-bearing update creates an Activity Tracker when the Work has no provider
  Tracker identity.
- The Tracker renders the complete current title and ordered Todo list.
- The Tracker includes the existing `View session` and `Conversation settings`
  actions.

### REQ-2. Tracker visibility remains monotonic within the cycle

Once Todo publication or an explicit invocation makes the Work Tracker-visible, the
cycle must not return to hidden or create a duplicate Tracker.

**Acceptance criteria**

- Later progress updates target the same provider message identity.
- A later explicit mention does not create a second Tracker.
- Confirmed provider absence follows the existing replacement lifecycle.

### REQ-3. Preserve lightweight checking and unaffected paths

The change must preserve existing behavior outside task-bearing Discord conversational
Work.

**Acceptance criteria**

- Initial non-mention checking work with no Agent-authored Todo may remain hidden.
- Typing remains active for hidden and visible Discord Work.
- Slack and Scheduled Task Tracker visibility remain unchanged.
- Existing final-reply cleanup and lifecycle deletion behavior remain unchanged.

## Fixed Constraints

- Canonical Channel Work task state is the sole authority for whether an unfinished
  Todo has been published.
- A valid `continue` transition always retains at least one unfinished task.
- Tracker provider effects remain commit-before-call, one-attempt effects.
- Existing Work and provider projection state remain authoritative.

## Open Assumptions

- None.

## Confirmation

Confirmed by the requester on 2026-08-29 with the explicit clarification that a Todo
list must produce an Activity Tracker even when the triggering Discord message was not
a mention, and with the instruction to proceed with the correction.
