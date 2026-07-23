---
title: "Readable Slack Channel Messages Requirements"
created: 2026-07-23
updated: 2026-07-23
implemented: 2026-07-23
tags: [slack, external-channel, frontend, agent]
document_role: primary
document_type: requirements
snapshot_id: slack-260723
---

# Readable Slack Channel Messages Requirements

- Snapshot: `slack-260723`
- Document reference: `slack-260723/REQ`

## Problem

Slack-originated messages expose provider IDs and operational metadata that make the Session timeline difficult to scan. Agent replies are not rendered with Slack Markdown, and Azents operational messages are plain text rather than native Slack UI.

## Primary Actor

An Agent administrator reviewing and operating a Slack-connected Agent conversation.

## Primary Scenario

A Slack participant mentions an Agent in a tracked thread. The administrator and Agent can understand people, channels, and references by name; the Agent replies in correctly rendered Markdown; and progress or approval interactions appear as clear native Slack UI.

## Supporting Scenarios

- An administrator opens an external-message detail view to inspect provider identity and message metadata.
- A participant grants access from an approval action in Slack.
- A model prepares a channel action and receives the provider-specific text limit before delivery.

## Goals

- Make external-message timeline content readable without hiding traceability.
- Preserve provider IDs for Agent actions while exposing name mappings in Agent context.
- Use Slack-native rendering appropriate to conversational and operational messages.

## Non-Goals

- Supporting external-channel providers other than Slack in this snapshot.
- Rewriting canonical raw provider message content.
- Adding a workspace-wide directory browser.

## Requirements

### REQ-1. Readable external-message timeline

The Session timeline must summarize a Slack message with its sender name, a message preview, and its message status, without showing the channel identity in the summary.

**Acceptance criteria**

- A summary shows the Slack icon, a sender name, a bounded text preview, and the message status.
- The expanded message shows the complete text and its original-message link directly below the text when available.
- Provider metadata is available through a separate detail view rather than the expanded message body.

### REQ-2. Human-readable Slack identities

The product must resolve and retain display names for Slack senders and channel references when Slack permits resolution.

**Acceptance criteria**

- Sender and current-channel labels prefer a human-readable Slack name and safely fall back to the provider ID.
- Detail presentation shows a sender display name together with an abbreviated provider ID.
- Visible external-message text renders resolved user and channel references instead of raw Slack IDs whenever a mapping is available.

### REQ-3. Agent identity context

An Agent receiving Slack-originated input must receive the relevant provider IDs and their resolved names together.

**Acceptance criteria**

- Agent-visible external-message context retains original provider IDs.
- Context includes mappings for the sender, current channel, and user/channel references found in the delivered message batch.
- Unresolved references remain usable by their original ID.

### REQ-4. Slack message rendering

Conversational Agent replies must use Slack Markdown rendering, and Azents-generated operational messages must use Slack Block Kit.

**Acceptance criteria**

- Conversational replies render supported Slack Markdown instead of exposing Markdown source syntax.
- Work-progress and access-control messages render with Block Kit and include accessible fallback text.
- Access approval actions are rendered as buttons, not raw URLs.

### REQ-5. Provider text limits

Channel-action text input and delivery validation must enforce the active provider/channel's supported maximum length.

**Acceptance criteria**

- The Tool schema advertises Slack's supported Markdown text maximum.
- Delivery rejects over-limit text before a Slack mutation request.

## Fixed Constraints

- Raw provider message bodies and durable provider identities remain unchanged.
- Slack credentials and tokens must never appear in prompts, UI, logs, or delivery records.
- The existing explicit `channel_action` publication boundary remains unchanged.
- Functional Slack messages provide fallback text for notifications and assistive technology.

## Open Assumptions

- Slack names may become stale after a provider-side rename until a later observed message or reference refreshes them.

## Confirmation

Confirmed by the requester on 2026-07-23 before ADR and design decisions began.
