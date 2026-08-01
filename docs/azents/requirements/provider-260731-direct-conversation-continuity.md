---
title: "Direct Provider Conversation Continuity Requirements"
created: 2026-07-31
updated: 2026-07-31
implemented: 2026-07-31
tags: [external-channel, slack, discord, conversation, reliability]
document_role: primary
document_type: requirements
snapshot_id: provider-260731
---

# Direct Provider Conversation Continuity Requirements

- Snapshot: `provider-260731`
- Document reference: `provider-260731/REQ`

## Problem

Slack and Discord participants need one accepted invocation to reach the connected Agent
Session exactly once, preserve the visible provider conversation context, and remain
recoverable across retries without Azents maintaining competing durable copies of inbound
provider messages.

## Primary Actor

An authorized Slack or Discord participant invoking or continuing an Agent conversation.

## Primary Scenario

1. A participant invokes or continues an Agent from Slack or Discord.
2. Azents resolves the provider conversation and bound Agent Session during the admitted
   request.
3. Azents reads the ordered provider-visible history through the trigger and accepts it as
   one Session input.
4. Azents triggers Session execution before acknowledging successful handling.
5. A duplicate or retried delivery does not create another Session input or execution.

## Supporting Scenarios

- An unbound Multi App conversation waits for Agent selection and resumes from the same
  provider trigger after selection.
- An unauthorized participant waits for approval and the original invocation resumes
  after Allow without retaining provider message content in the approval record.
- An Agent downloads a Slack or Discord file identified in the model-visible provider
  file key; provider authentication and permissions determine whether the download is
  allowed.

## Goals

- Keep provider history as the inbound content authority.
- Keep one canonical Session input and execution identity for each accepted trigger.
- Preserve selector and approval replay without a second inbound message store.
- Remove durable state that no longer owns routing, replay, recovery, or delivery.

## Non-Goals

- Retaining a compatibility path for the replaced External Channel file-key shape.
- Restricting provider-authorized file downloads to attachments already present in the
  current Session history.
- Reconstructing removed provider content from Azents after it is unavailable upstream.

## Requirements

### REQ-1. One synchronous Session handoff

A successfully acknowledged provider trigger must have resolved its conversation and
Session, accepted one ordered mailbox input, and initiated Session execution.

**Acceptance criteria**

- Slack HTTP, Slack Socket Mode, Discord HTTP, and Discord Gateway use the same handoff
  outcome.
- Provider message content comes from provider history, not the inbound callback body.
- One accepted trigger produces one mailbox input and one execution trigger.

### REQ-2. Mailbox-owned idempotency and recovery

The canonical mailbox input must be the durable identity for accepted Session input and
wake recovery.

**Acceptance criteria**

- Duplicate delivery reuses the same mailbox identity.
- Conversation read position advances only with successful mailbox acceptance.
- A failed wake can be retried while the mailbox input remains pending.
- No invocation-batch or separate wake-dispatch record is required.

### REQ-3. Content-free selector and approval replay

Selection and approval must preserve enough typed provider identity to replay the
original trigger without storing its provider content.

**Acceptance criteria**

- Selector state retains its connection, resource, principal, conversation position,
  provider message key, trigger position, and selected route.
- Access requests retain the equivalent replay boundary and resume automatically after
  Allow.
- Replay validates the retained owners before reading provider history.

### REQ-4. Single inbound persistence authority

Azents must not retain obsolete durable inbound content, batch, admission, provisioning,
or wake state after the mailbox handoff becomes authoritative.

**Acceptance criteria**

- The retired inbound tables, models, repository methods, foreign keys, enums, fixtures,
  and processing paths are absent from the installed application schema and runtime.
- Provider locators, conversation positions, access requests, interactions, bindings,
  delivery attempts, Session events, and mailbox items retain their current owners.
- Cutover stops before destructive DDL when in-flight legacy work cannot be discarded
  safely.

### REQ-5. Provider-addressed file keys

A model-visible file key must carry the provider coordinates needed to perform the
provider request directly.

**Acceptance criteria**

- Discord keys contain binding, channel, message, and attachment identity.
- Slack keys contain binding and provider file identity.
- Discord download does not query Session event history to recover provider coordinates.
- The active connection's provider authentication and permissions determine access.

## Fixed Constraints

- The implemented `channel-260729` snapshot remains immutable historical context.
- Provider payloads, credentials, attachment URLs, and message bodies must not appear in
  logs, migration errors, or operational evidence.
- The replacement is direct; no legacy storage or file-key fallback is retained solely
  for compatibility.
- PostgreSQL remains the durable authority for conversation positions, access decisions,
  interactions, mailbox items, and Session events.

## Open Assumptions

- Slack and Discord continue to expose the required history and file APIs to the
  authenticated connected App or Bot.
- Provider message and file identities remain stable for the duration of a request.

## Confirmation

Confirmed by the requester on 2026-07-31 through the explicit replacement-first scope,
table-removal list, mailbox authority requirement, and provider-authenticated file-key
decisions before this snapshot's ADR and Design were recorded.
