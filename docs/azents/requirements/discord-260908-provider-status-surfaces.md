---
title: "Discord Provider Status Surfaces Requirements"
created: 2026-09-08
updated: 2026-09-08
implemented: 2026-09-08
tags: [discord, external-channel, channel-work, scheduled-task, typing]
document_role: primary
document_type: requirements
snapshot_id: discord-260908
---

# Discord Provider Status Surfaces Requirements

- Snapshot: `discord-260908`
- Document reference: `discord-260908/REQ`

## Problem

Discord currently creates a visible Channel Work card automatically when a participant explicitly mentions the Agent, even though Discord typing already communicates that the Agent is working. Scheduled Task execution also reuses the generic Channel Work title and places generic running copy before the actual Schedule title, making the provider surface less direct than the task-specific information.

## Primary Actor

A Discord participant observing an Agent invocation or a Scheduled Task execution in a connected conversation.

## Primary Scenario

The participant mentions the Agent and sees Discord typing as the only automatic in-progress signal. When a Scheduled Task starts, the participant sees a task-specific card titled `Scheduled Task` whose body shows the Schedule title followed by its recurring schedule or one-time execution time.

## Supporting Scenarios

- An Agent may still explicitly publish structured Channel Work through `channel_action` when progress details are materially useful.
- Slack retains its existing automatic conversational Tracker behavior.
- Scheduled Task progress published after the initial execution card retains its existing structured progress behavior.

## Goals

- Remove duplicate automatic progress surfaces from Discord mention-triggered execution.
- Keep Discord typing as the lightweight automatic activity signal.
- Make the initial Scheduled Task execution card immediately identify the Schedule and timing.

## Non-Goals

- Removing canonical Channel Work state used for execution and recovery.
- Removing explicit `channel_action` progress publication.
- Changing Slack typing, presence, or Tracker behavior.
- Changing Scheduled Task scheduling semantics, execution, registration, deletion, or terminal delivery.
- Changing non-initial Scheduled Task progress layout.

## Requirements

### REQ-1. Use typing as Discord's only automatic conversational activity signal

A Discord conversational invocation must not automatically create or promote a visible Channel Work Tracker solely because the provider message explicitly mentioned the Agent.

**Acceptance criteria**

- A new Discord Binding created from a mention starts with hidden Tracker visibility.
- A mention on an existing Discord Binding does not promote hidden Work to a visible Tracker.
- Active ready Discord conversational Work remains eligible for the existing typing registry.
- An explicit `channel_action` progress update may still publish a Channel Work Tracker.
- Slack behavior remains unchanged.

### REQ-2. Present the initial Scheduled Task card with task-specific identity

The initial Discord card for a running Scheduled Task must use the task-specific title and schedule information instead of generic Channel Work running copy.

**Acceptance criteria**

- The Embed title is exactly `Scheduled Task`.
- The first body line is the Scheduled Task title.
- The next body line is the human-readable recurring schedule or one-time execution time.
- The existing `View session` navigation remains available.
- The card does not display `Agent is running a scheduled task…` or the generic `Channel Work` title.

## Fixed Constraints

- Discord typing remains ephemeral; canonical Work and Scheduled Task state remain durable authorities.
- Tracker suppression is provider-specific and must not alter Slack behavior.
- Schedule text uses the existing canonical human schedule renderer.
- No database migration, compatibility fallback, rollout flag, or scheduling data change is introduced.

## Confirmation

Confirmed by the requester on 2026-09-08 through two direct corrections: remove the automatic Channel Work card for Discord mentions and use typing consistently; then change the initial Scheduled Task card to `Scheduled Task` with the Schedule title and schedule timing in its body.
