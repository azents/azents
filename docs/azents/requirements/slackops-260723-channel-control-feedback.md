---
title: "Slack Channel Control Feedback Requirements"
created: 2026-07-23
updated: 2026-07-23
tags: [slack, external-channel, frontend, authorization]
document_role: primary
document_type: requirements
snapshot_id: slackops-260723
---

# Slack Channel Control Feedback Requirements

- Snapshot: `slackops-260723`
- Document reference: `slackops-260723/REQ`

## Problem

Slack messages that contain only Block Kit rich text can appear empty in Azents,
operational progress state can be misleading, and approval or management surfaces
do not provide enough identity and lifecycle feedback for safe administration.

## Primary Actor

An Agent administrator operating a Slack-connected Agent from the Azents Web
interface.

## Primary Scenario

A previously unknown Slack participant invokes an Agent from a rich Slack thread.
The administrator can identify the participant by name and full Slack ID, choose
one of the four supported access decisions, and observe accurate Agent progress
without stale approval or Activity Tracker messages remaining in Slack.

## Supporting Scenarios

- An administrator inspects and copies full provider identifiers from an external
  message.
- An administrator revokes a participant grant and confirms destructive External
  Channel actions through Azents-styled dialogs.
- A mobile user scrolls the Session tabs without a visible browser scrollbar and
  reads the complete approval status label.

## Goals

- Preserve readable content from supported Slack Block Kit and rich-text messages.
- Make Slack identity and operational lifecycle state inspectable and accurate.
- Complete approval and permission-management lifecycles without stale controls.
- Correct the reported responsive UI defects.

## Non-Goals

- Supporting non-Slack provider block formats.
- Retrying ambiguous provider mutations automatically.
- Reconstructing unsupported interactive Slack elements as executable Azents UI.
- Deleting provider messages, canonical message history, or projected Session
  history when a participant grant is revoked.

## Requirements

### REQ-1. Bounded Slack rich-text normalization

Slack messages without usable fallback text must retain readable text from supported
Block Kit and rich-text elements.

**Acceptance criteria**

- HTTP callback and Socket Mode ingestion produce the same normalized text for the
  same supported Slack payload.
- User and channel elements preserve their provider IDs in reference syntax so name
  resolution continues to work.
- Unsupported or oversized block content is ignored or bounded without rejecting an
  otherwise valid provider event.
- Edit revision identity changes when the normalized rich-text body changes.

### REQ-2. Full inspectable provider identity

Administrative detail surfaces must show complete Slack/provider identifiers without
visual abbreviation and provide a copy action.

**Acceptance criteria**

- External-message details show and copy the full participant and message identity
  when available.
- Approval details show the participant display name together with the full Slack
  user ID.
- Long identifiers wrap instead of truncating.

### REQ-3. Accurate Activity Tracker presentation

Session Channels must present the current Channel Work tasks and the actual Slack
progress projection lifecycle.

**Acceptance criteria**

- Ordered task titles and states are visible.
- Projection status distinguishes synchronized, missing, stale, deletion failure,
  unknown outcome, and no active projection from the durable delivery ledger.
- Normal revision counters are not interpreted as drift merely because they use
  different sequences.

### REQ-4. Complete approval decision lifecycle

Approval supports Agent-level allow, Session-level allow, deny, and block. Every
final decision removes the Bot-owned Slack approval control message when it was
successfully created.

**Acceptance criteria**

- Slack approval content identifies the target participant by display name and full
  Slack ID.
- The decision transaction durably records the final decision and a provider-delete
  intent together.
- Slack deletion happens only after the decision commit.
- A failed or ambiguous Slack deletion never rolls back the decision and remains
  inspectable as a delivery outcome.

### REQ-5. Explicit permission and destructive-action management

Revoking an active participant grant removes the grant record, and External Channel
destructive actions use Azents-styled confirmation dialogs.

**Acceptance criteria**

- Revocation prevents future invocation and removes the grant from management lists.
- Canonical external messages and already projected Session history remain intact.
- Connection disconnect, binding disconnect, grant revoke, and block removal do not
  use a native browser confirmation dialog.

### REQ-6. Responsive approval and Session navigation

Approval status and Session tabs remain usable on narrow screens.

**Acceptance criteria**

- Approval status text is not truncated; the header may wrap when necessary.
- Session tabs remain horizontally scrollable by touch, trackpad, and mouse.
- The horizontal scrollbar is hidden in Firefox and WebKit-based browsers.

## Fixed Constraints

- Slack credentials and secrets never enter persisted delivery payloads, UI state,
  prompts, logs, or test evidence.
- Provider mutation attempts remain durable, at-most-once operations.
- Raw provider identifiers remain available for Agent actions and traceability.
- The four approval decisions retain their existing authorization semantics.

## Open Assumptions

- Slack may omit accessible fallback text even when a message contains supported
  rich-text blocks.

## Confirmation

Confirmed by the requester through the accumulated feedback and explicit
implementation authorization on 2026-07-23.
