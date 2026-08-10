---
title: "Batched External Channel Conversation Ingress Requirements"
created: 2026-08-10
updated: 2026-08-10
tags: [external-channel, reliability, messaging]
document_role: primary
document_type: requirements
snapshot_id: channel-260810
---

# Batched External Channel Conversation Ingress Requirements

- Snapshot: `channel-260810`
- Document reference: `channel-260810/REQ`

## Problem

External Channel conversation messages currently depend on provider history,
coordination, canonical mailbox admission, and Session wake delivery completing inside
one synchronous provider callback boundary. Provider latency or a transient downstream
failure can delay or lose work before a durable processing identity exists. Repeating
the complete ingress-processing, recovery, and Session-wake cycle for every queued
trigger also handles backlog inefficiently when new messages accumulate faster than
the current processing attempt can resolve and admit them.

## Primary Actor

A participant sending ordinary conversation messages to an Azents Agent through a
supported External Channel provider.

## Primary Scenario

A participant sends one or more messages through Discord or Slack.
The provider callback first applies current connection, conversation, response-mode,
invocation eligibility, active Binding, and target Session filters. Azents durably
retains every Session-bound trigger that passes that callback admission and immediately
starts processing when the Session ingress queue has no active batch. The first batch
after an idle boundary contains the first available trigger without waiting to
accumulate more messages. Triggers arriving while that batch is processed remain
ordered in the queue; when processing finishes, Azents immediately claims the next
bounded batch from the accumulated backlog. Each batch selects every message's
provider-specific resolution policy, converts the successfully admitted messages into
canonical input messages, creates one mailbox item for every resolved canonical
provider message, commits all mailbox items produced by successful ingress items, and
wakes the Session once after the processing batch completes. Provider latency,
transient process failure, and unavailable ephemeral routing infrastructure do not
require the participant to resend the messages.

## Supporting Scenarios

- A single low-volume conversation message is processed immediately as a one-message
  ingress batch. Its provider history and exact trigger may still produce multiple
  mailbox items before the post-batch wake.
- A provider exact-message or history operation is rate limited or temporarily
  unavailable; retained triggers wait and retry without being lost.
- One bounded processing batch may contain triggers from Discord, Slack, several
  provider conversations, or future providers. Each resolved canonical provider
  message remains an individual mailbox item.
- A message without a resolved Session follows its setup, selection, access, or Binding
  establishment lifecycle outside the Session-bound ingress queue. Its original trigger
  may enter grouped ingress only after that lifecycle resolves a Session.
- A future External Channel provider adopts the same durable processing-batch,
  per-message mailbox, and post-batch wake contract while defining its own
  message-resolution behavior.

## Goals

- Decouple durable message receipt from provider history latency and Session wake
  availability.
- Exclude unrelated or currently non-triggering provider traffic before it occupies
  durable ingress capacity.
- Drain ordered backlog in bounded processing batches when messages accumulate during
  earlier processing, without delaying an idle queue to wait for a larger batch.
- Give Discord, Slack, and future providers one consistent reliability and grouping
  contract.
- Keep provider-specific message resolution explicit without duplicating the durable
  lifecycle and recovery contract.
- Suppress queued triggers already covered by a later successful canonical
  conversation-position advance instead of creating duplicate Agent input.
- Produce one effective Session wake after each processing batch that commits at least
  one mailbox item.

## Non-Goals

- Slash Commands, message commands, shortcuts, components, modals, autocomplete, setup
  controls, and other interactive callbacks are outside this snapshot.
- Raw provider callbacks, credentials, signatures, interaction tokens, private URLs,
  and unbounded provider message content do not become canonical Session input.
- This snapshot does not require new messages to enter a model call that is already in
  flight.
- This snapshot does not make Redis or another ephemeral broker a correctness source.

## Requirements

### REQ-1. Provider callbacks filter conversation traffic before durable receipt

Each provider callback must authenticate and minimally classify a conversation message
and resolve its active Binding and target Session before creating durable ingress work.
Only messages that pass the current connection, provider conversation, message-kind,
response-mode, invocation eligibility, Binding, and Session filters enter the grouped
ingress lifecycle.

**Acceptance criteria**

- Discord excludes traffic outside the configured Guild and connected conversation
  scope and applies current mention and response-mode eligibility before queueing.
- Slack excludes traffic outside the authenticated Team and connected conversation
  scope and applies current mention and response-mode eligibility before queueing.
- Every durable ingress trigger carries one immutable target Session identity resolved
  before queue insertion.
- The callback admission decision is authoritative for that queued trigger. Grouped
  processing does not re-evaluate response mode, mention eligibility, Binding
  selection, or participant access merely because those settings changed after durable
  receipt.
- An unconnected conversation creates no ingress queue item while setup, selection,
  access, or Binding establishment has not resolved a Session.
- Connected Bot/App output, unsupported message revisions or types, unrelated
  conversations, and currently non-triggering `mention_only` traffic create no durable
  ingress work.
- Mention or invocation shape alone is insufficient for admission. The callback must
  also enforce the current response mode, participant access or block state, Binding,
  and target Session eligibility before the trigger enters ingress.
- A future provider defines an equivalent typed callback-admission policy before using
  the shared grouped lifecycle.

### REQ-2. Admitted conversation triggers survive synchronous provider latency

An authenticated eligible Session-bound conversation-message trigger must acquire a
durable processing identity before provider exact-message or history operations
determine its canonical input.

**Acceptance criteria**

- A provider history timeout, rate limit, transient provider failure, process restart,
  or ephemeral broker outage after durable receipt does not erase the trigger.
- Failure while admitting one typed provider callback does not prevent later callbacks
  already delivered by that provider transport from independently attempting durable
  ingress receipt.
- Once durable ingress receipt commits, failure to start or continue asynchronous
  processing does not invalidate or erase the trigger; durable ingress recovery retries
  processing.
- Duplicate provider delivery converges on the same durable processing identity while
  that ingress lifecycle remains active. A later redelivery after bounded failure and
  queue removal may create a new lifecycle as defined by REQ-6.
- Every retained trigger eventually reaches canonical admission, cursor suppression,
  or a bounded failure that is logged before the queue item is removed.

### REQ-3. Pending triggers are processed in bounded groups

Pending conversation triggers for one Session must be claimed and processed in groups
with a fixed upper bound rather than requiring one independent processing lifecycle and
Session wake per queued message once backlog has accumulated.

**Acceptance criteria**

- One processing attempt never claims more than the configured safety bound.
- Every claimed batch belongs to exactly one Session.
- Provider, connection, and conversation identities do not partition one Session's
  claimed batch.
- Durable ingress order is independent from provider-conversation position order.
  Items in one processing batch are not resorted by provider position.
- An idle Session queue begins processing its first available trigger immediately and
  does not wait for an accumulation window.
- The first batch after an idle boundary claims exactly one trigger.
- Every later batch claims at most ten currently pending triggers.
- Triggers arriving after a batch claim remain queued for the next batch.
- When a batch finishes and pending triggers remain, the next bounded batch begins
  immediately.
- Additional pending triggers remain available for a later group.
- A low-volume single trigger uses the same lifecycle as a full group.
- Claim loss or process termination leaves unfinished triggers recoverable.

### REQ-4. Each provider defines typed message resolution under one shared contract

Discord, Slack, and future providers must resolve each retained trigger through an
explicit provider-specific policy while producing the same provider-neutral canonical
message contract.

**Acceptance criteria**

- Discord and Slack use their own exact-message, history, identity, rate-limit, and
  error-classification behavior.
- Provider resolution correlates every returned canonical history message with durable
  ingress triggers for the same connection and provider conversation.
- A history message matching an admitted invocation trigger retains that trigger's
  invocation identity and is marked as an invocation rather than ordinary context in
  the Agent prompt, even when a later-position trigger caused the provider-history
  read.
- `context` versus `invocation` is prompt-role metadata only. It does not grant or deny
  access, change ingress admission, alter mailbox eligibility, select a Session, or
  create a separate permission model after the trigger entered ingress.
- The canonical External Channel message contract names this distinction
  `prompt_role` with values `context` and `invocation`. The existing
  `authorization`, `context_only`, and `authorized_invocation` names are removed rather
  than retained as aliases or compatibility fields.
- Provider message content is not reinterpreted during history processing to create an
  invocation prompt role. A message receives that role only when its provider identity
  matches a durable ingress trigger that already passed callback admission.
- A provider-history message with no matching admitted ingress trigger remains context,
  including a visible mention from a participant who was not eligible to create
  ingress.
- Provider-specific processing cannot bypass current authority, response-mode, access,
  bounded-history, or message-eligibility rules.
- Processing verifies the canonical provider trigger identity, current conversation
  cursor, and the technical availability of the retained connection and target Session.
  It does not introduce configuration-generation reconciliation or reroute a retained
  trigger to a different Session.
- Adding a future provider requires a provider message-resolution policy but does not
  require a new durable grouping, retry, or recovery contract.

### REQ-5. Successful ingress items produce per-message mailbox items and one post-batch wake

Every canonical provider message resolved from a successful ingress item must become
its own independent durable mailbox item. Provider history is not embedded as several
messages inside the exact trigger's mailbox item: every history message has its own
mailbox identity and FIFO lifecycle, and the exact trigger has another independent
mailbox item. One successful ingress item may therefore produce multiple mailbox items.
Retryable or terminally failed ingress items produce no mailbox items. After all items
in the processing batch reach their current outcomes, the successful mailbox items
commit together and Azents issues one effective Session wake for that processing
batch.

**Acceptance criteria**

- Every successful ingress item produces one or more mailbox items.
- Each resolved history message creates its own independent mailbox item with its own
  provider position, provenance, idempotency identity, and FIFO lifecycle.
- A history mailbox item whose provider message identity matches an admitted invocation
  ingress item carries that ingress item's invocation identity and invocation prompt
  role instead of the context prompt role.
- The exact trigger message creates its own independent mailbox item rather than
  serving as an envelope for its preceding history.
- An ingress item resolving `n` history messages plus its exact trigger creates `n + 1`
  ordered mailbox items.
- No External Channel mailbox item contains more than one canonical provider message.
- Mailbox item order follows the processing batch's durable ingress order and each
  ingress item's canonical provider-history order.
- A successful ingress item advances its provider-conversation cursor before a later
  item from the same conversation is evaluated, even when both items belong to the
  same processing batch.
- Multiple successful exact triggers remain separate mailbox items rather than being
  collapsed into one mailbox item.
- Retryable ingress items create no mailbox items until a later successful attempt.
  Bounded-failure items create no mailbox items and leave no completed ingress outcome
  after queue removal.
- All mailbox items produced by successful ingress items in the processing batch are
  durably admitted together; partial mailbox admission for that successful subset is
  not observable.
- The processing batch wake is issued only after that mailbox admission commits.
- A processing batch that commits at least one mailbox item creates one effective
  Session wake. A batch with no successful mailbox items creates no wake.
- Failure of the post-commit wake does not erase or duplicate committed mailbox items;
  the effective wake remains recoverable.

### REQ-6. Individual message failures do not silently discard the group

Provider resolution or admission failure for one retained trigger must have an
explicit bounded effect on the rest of the claimed group.

**Acceptance criteria**

- No retained trigger disappears because an earlier trigger in the same group failed.
- Mailbox items from successfully resolved triggers commit without waiting for
  retryable or terminally failed triggers in the same processing batch.
- Retryable failures remain durably visible while waiting and re-enter the tail of the
  same Session ingress queue after their retry delay instead of blocking later
  triggers.
- A retained trigger receives no more than five provider attempts including its first
  attempt and remains automatically retryable for no more than five minutes from
  durable ingress creation.
- Known transient failures use short bounded retry delays. Provider `Retry-After` is
  honored only when the requested wait remains within the trigger's five-minute retry
  lifetime; a longer required wait produces a bounded failure rather than
  starting the Session unexpectedly much later.
- A later trigger from the same provider conversation may resolve successfully and
  advance the canonical conversation position beyond an earlier retryable trigger.
- When a retried trigger is already at or behind the current canonical conversation
  position, it is suppressed as already covered and creates no additional mailbox
  input or Session wake.
- A trigger whose attempt or age budget is exhausted emits one sanitized structured
  failure log and is removed from the ingress queue without advancing the conversation
  cursor.
- No successful, suppressed, or failed queue outcome is retained after its processing
  lifecycle finishes.
- If the provider later redelivers a failed trigger that is still ahead of the current
  conversation cursor, it may enter a new ingress lifecycle with a new retry budget.
- Successfully resolved messages are not duplicated across retry attempts.

### REQ-7. The canonical conversation cursor suppresses already-covered triggers

Before a retained trigger produces canonical Session input, its position must be
compared with the current canonical read-through position for the same provider
conversation. A trigger at or behind that cursor is already covered and must be
suppressed rather than creating another input boundary.

**Acceptance criteria**

- Suppression compares positions only within the same canonical provider connection and
  conversation identity.
- A later successfully admitted trigger may advance the conversation cursor beyond an
  earlier retryable trigger that re-entered the Session queue tail.
- Provider callbacks may reach durable ingress out of provider-position order. If an
  earlier queue item has a later provider position and successfully advances the cursor,
  a later queue item with an older or equal provider position is suppressed as already
  covered.
- Cursor suppression removes the later processing attempt, not invocation meaning
  already materialized from that trigger's message in an earlier successful history
  range.
- When `trigger_position` is at or behind the current read-through position, the queued
  trigger creates no canonical message, mailbox input, independent invocation, or
  Session wake.
- Cursor coverage is checked before avoidable provider history work and is revalidated
  at the final canonical admission boundary.
- Only a successful canonical admission may advance the read-through position.
  Retryable failure, terminal failure, queue movement, and suppression do not advance
  the cursor.
- Same-conversation items in one processing batch observe cursor advances from earlier
  queue items; batch preparation cannot use one stale cursor snapshot for every item.
- A cursor-covered trigger is removed from the ingress queue without creating a
  retained suppression outcome. A later duplicate is suppressed again by the same
  cursor authority.
- Concurrent or stale processing cannot admit the same covered provider range twice.

### REQ-8. Grouped ingress remains observable and operationally bounded

Operators must be able to inspect active retained conversation triggers while they are
pending, processing, or waiting to retry without accessing message bodies or
credentials. Completed queue outcomes are not retained; bounded failures emit
sanitized structured logs.

**Acceptance criteria**

- Safe active-queue diagnostics expose counts, provider, connection identity, age,
  attempts, and processing-batch identity.
- Backlog size, oldest pending age, retry volume, failure volume, group size, and
  processing duration are measurable without retaining completed queue rows.
- Every bounded failure emits one sanitized structured log without message bodies,
  credentials, private URLs, or raw provider payloads.
- Queue cleanup removes only items whose successful, suppressed, or bounded-failure
  processing lifecycle has finished.

## Fixed Constraints

- Provider history remains the canonical inbound content authority.
- Durable ingress state retains content-free typed trigger identity rather than raw
  provider callbacks or message bodies.
- PostgreSQL remains the durable ordering, idempotency, and recovery authority.
- Every durable ingress queue item is Session-bound before insertion.
- Redis and other brokers may reduce latency but cannot be required for correctness.
- Existing provider authentication, lease/configuration fencing, access, response-mode,
  conversation-position, mailbox, and Session authority remain enforced.
- The canonical provider-conversation read-through position is the authority for
  deciding whether a queued trigger range has already been covered.
- Provider SDK public APIs remain authoritative wherever the adopted SDK supports the
  required operation.

## Open Assumptions

- None.

## Confirmation

Confirmed by the requester on 2026-08-10 after the completed-outcome retention contract
was revised.
