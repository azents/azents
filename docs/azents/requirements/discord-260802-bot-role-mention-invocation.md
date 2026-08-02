---
title: "Discord Bot Role Mention Invocation Requirements"
created: 2026-08-02
updated: 2026-08-02
tags: [discord, external-channel, agent]
document_role: primary
document_type: requirements
snapshot_id: discord-260802
---

# Discord Bot Role Mention Invocation Requirements

- Snapshot: `discord-260802`
- Document reference: `discord-260802/REQ`

## Problem

Discord creates a managed role for an installed Bot. The role can have the same
visible name as the Bot account, so a participant may select the role from Discord's
mention picker while intending to invoke the connected Agent. Azents currently treats
only a direct mention of the Bot account as an explicit invocation, causing the
visually similar managed-role mention to remain context without starting work.

## Primary Actor

A human participant in a Discord conversation connected to an Azents Agent.

## Primary Scenario

The participant mentions the connected Bot's Discord-managed role in a conversation
configured for mention-only participation. Azents recognizes the role as belonging to
that exact Bot and admits the message through the same authorization, Session, Channel
Work, and response flow used by a direct Bot-account mention.

## Supporting Scenarios

- The managed-role mention can start initial conversation setup in a parent channel.
- The managed-role mention can invoke an existing binding in a parent channel or
  thread.
- Direct Bot-account mentions continue to work unchanged.

## Goals

- Make the connected Bot's own Discord-managed role an unambiguous explicit
  invocation target.
- Preserve every existing sender eligibility, access, setup, response-mode, history,
  execution, and delivery boundary.
- Prevent arbitrary roles and other Bots' roles from invoking the Agent.

## Non-Goals

- Treating every role assigned to the Bot as an invocation target.
- Treating manually created roles or another Bot's managed role as an invocation.
- Creating, deleting, renaming, or changing mention permissions for Discord roles.
- Adding a role-selection setting or persisting a configured Discord role identifier.
- Changing Slack invocation behavior or `all_messages` participation.

## Requirements

### REQ-1. Connected Bot managed-role invocation

A mention of the Discord-managed role owned by the connected Bot must count as an
explicit provider invocation.

**Acceptance criteria**

- The first eligible managed-role mention can start initial Discord conversation
  setup without a preceding direct Bot mention.
- A managed-role mention on an existing `mention_only` binding invokes the same Agent
  Session through the normal admission flow.
- The invocation works in configured parent channels and Discord threads.
- The trigger message remains the canonical invocation message and earlier ordinary
  messages remain eligible bounded history context.

### REQ-2. Exact Bot ownership boundary

Only a managed role whose provider-declared Bot owner matches the connection's
validated Bot identity may count as an invocation.

**Acceptance criteria**

- A manually created role does not invoke the Agent.
- A role merely assigned to the Bot does not invoke the Agent unless Discord declares
  it as that Bot's managed role.
- Another Bot's managed role does not invoke the Agent.
- Role display names, colors, positions, and ordinary role membership do not affect
  invocation classification.

### REQ-3. Existing behavior preservation

Managed-role invocation must reuse the existing explicit-invocation contract without
weakening any downstream policy.

**Acceptance criteria**

- Direct Bot-account mentions continue to invoke the Agent.
- Existing all-users, restricted-access, grant, block, human-author, setup, and
  binding response-mode checks retain their current precedence.
- Bot, app, system, blocked, and otherwise ineligible authors remain unable to invoke
  the Agent solely by mentioning the role.
- Admission remains idempotent and creates no duplicate mailbox input, Session wake,
  Channel Work, or AgentRun for the same provider message.

## Fixed Constraints

- The connection's validated `provider_bot_user_id` remains the Bot identity
  authority.
- Discord provider metadata, not visible role text, determines managed-role ownership.
- The change must not add provider REST I/O, durable role configuration, or a second
  admission path.
- Existing provider-neutral invocation handling remains authoritative after Discord
  event normalization.
- Product verification must include deterministic Discord Gateway provider-fake E2E
  evidence.

## Open Assumptions

- Discord includes the mentioned managed role and its Bot ownership tag in the typed
  Gateway message and Guild role state available to the supported SDK.

## Confirmation

Confirmed by the requester on 2026-08-02 before ADR and design decisions began.
