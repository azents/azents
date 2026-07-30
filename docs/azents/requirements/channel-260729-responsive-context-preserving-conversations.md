---
title: "Responsive Context-Preserving External Conversations Requirements"
created: 2026-07-29
updated: 2026-07-29
implemented: 2026-07-30
tags: [external-channel, slack, discord, conversation, reliability]
document_role: primary
document_type: requirements
snapshot_id: channel-260729
---

# Responsive Context-Preserving External Conversations Requirements

- Snapshot: `channel-260729`
- Document reference: `channel-260729/REQ`

## Problem

External-channel participants can submit a valid Agent invocation and receive no timely
provider-visible acknowledgement because inbound transport, deferred event processing,
conversation provisioning, context hydration, Session activation, and provider delivery
are separated by background polling and reconciliation. The delay hides whether the
request was accepted and can also postpone unrelated Slack and Discord messages behind
shared serial processing.

Participants need a valid Slack or Discord invocation to establish its provider
conversation, preserve the messages they can see, durably reach the bound Azents
Session, and trigger execution within the provider acknowledgement window. Socket-based
provider delivery must offer the same outcome as direct webhook delivery rather than a
weaker deferred path.

## Primary Actor

An authorized Slack or Discord participant who explicitly invokes an Azents Agent from
an unbound provider channel or thread and then continues the conversation in the bound
thread.

## Primary Scenario

1. An authorized participant explicitly invokes an Agent from an unbound parent channel.
2. Azents resolves the route, creates or reuses the provider thread, and resolves or
   creates the bound Session during the admitted request.
3. Azents reads the provider-visible channel messages after the channel's last durable
   read position through the invoking message, excludes only messages authored by the
   connected Azents App or Bot, and ingests the ordered result as one Session input.
4. Azents durably advances the channel read position and triggers Session execution
   before acknowledging successful handling to the provider transport.
5. The Agent executes asynchronously and delivers progress and its reply in the resolved
   thread.
6. Later authorized participant messages in the bound thread continue the same Session
   without another mention, using a separate durable thread read position.

## Supporting Scenarios

- An authorized participant explicitly invokes an Agent inside an existing manually
  created but unbound provider thread; Azents reuses that thread rather than creating a
  new one.
- An unauthorized participant invokes an Agent and waits for approval. The approval
  request retains the original conversation and history boundary. Allow automatically
  ingests and executes the original request even if the shared channel read position
  advanced while approval was pending.
- Messages from unauthorized humans, other bots, and provider-visible system authors do
  not trigger ingestion by themselves, but they are included when they fall inside a
  later authorized trigger's provider-visible history range.
- A history range larger than the supported input window contributes only its newest
  messages together with a leading system notice that older messages were omitted.
- A transient provider, persistence, Session, or mailbox failure leaves the read position
  unchanged and fails the admitted request so normal transport redelivery or a later
  authorized trigger can recover the same range.

## Goals

- Make valid Slack and Discord invocations visibly responsive within their provider
  acknowledgement limits.
- Give direct webhook delivery and socket-based delivery the same conversation and
  Session-ingestion behavior.
- Preserve provider-visible conversation context without retaining a deferred raw-event
  inbox.
- Keep authorized triggers idempotent and ordered despite duplicate, delayed, or
  concurrent provider delivery.
- Preserve automatic execution of an original invocation after participant approval.
- Support equivalent external-channel conversation locking with either a Redis-backed
  or in-memory lock backend.

## Non-Goals

- Reflecting edits or deletions for messages that are already at or before a conversation
  read position.
- Retaining more than the bounded recent history window when a trigger spans a larger
  unread range.
- Distinguishing messages produced by different Agents that share one connected provider
  App or Bot identity.
- Retaining raw provider events for deferred processing, later replay, or an alternative
  event-driven source of message content.
- Performing Agent model execution or waiting for the Agent's reply before acknowledging
  successful message ingestion.
- Removing Redis from the existing Session broker, Agent Worker dispatch, or unrelated
  Azents runtime infrastructure.

## Requirements

### REQ-1. Timely admitted-request handoff

A valid external-channel invocation must complete conversation resolution, durable
Session input acceptance, and the Session execution trigger before successful provider
acknowledgement, while Agent execution remains asynchronous.

**Acceptance criteria**

- Under normal provider and database availability, admitted Slack and Discord requests
  complete the synchronous handoff within the applicable provider acknowledgement
  deadline.
- A successful acknowledgement means the provider conversation is resolved, the bound
  Session is resolved or created, one durable input batch exists, and execution has been
  triggered.
- The webhook path does not wait for Agent model execution, progress generation, or the
  final reply.
- Socket-delivered and directly delivered webhook requests expose the same success and
  failure meaning.

### REQ-2. Deterministic conversation boundary

A first invocation must establish one provider-visible conversation boundary, and later
messages must continue that same immutable Session conversation.

**Acceptance criteria**

- A first invocation from an unbound parent channel creates or reuses the thread rooted
  at the invoking message.
- A first invocation inside an existing manually created thread reuses that thread.
- An unbound parent channel or manually created thread requires an explicit Agent
  invocation before it becomes bound.
- Once bound, an authorized participant's ordinary thread message continues the same
  Session without mentioning the Agent.
- Provider controls, progress, replies, and files target the resolved thread.

### REQ-3. Provider-history-based ordered ingestion

An authorized trigger must ingest the provider-visible messages after the conversation's
last durable read position through the trigger message instead of treating the inbound
event body as the message-content source.

**Acceptance criteria**

- Each parent channel and each bound thread maintains an independent durable read
  position.
- A trigger at or before the current read position produces no input and does not trigger
  Session execution.
- A trigger after the current read position reads the ordered provider history in the
  exclusive-start, inclusive-trigger range.
- The invoking message is sourced from the same provider-history read as the preceding
  messages rather than from the inbound event body.
- The ordered messages and any omission notice enter the Session as one mailbox input
  batch and produce one execution trigger.
- The durable read position advances to the trigger only after the complete input batch
  is accepted.

### REQ-4. Provider-visible message fidelity

The Agent must receive the same messages a participant can see in the ingested provider
history range, except for output authored by the connected Azents App or Bot.

**Acceptance criteria**

- Messages are not excluded because their human author lacks Agent access.
- Messages from other bots and provider-visible system authors are included when the
  provider presents them in the conversation history.
- Visible message content, files, attachments, embeds, and equivalent provider-native
  presentation that participants can see are preserved through the canonical Session
  input contract.
- Every message authored by the connected Slack App or Discord Bot identity is excluded,
  including output produced for a different Agent through the same App identity.
- The system does not query delivery history to distinguish individual Agents behind one
  shared provider identity.

### REQ-5. Bounded unread history

A trigger spanning an excessive unread range must preserve the newest useful context and
make omitted history visible to the Agent.

**Acceptance criteria**

- At most the newest 20 provider messages through the trigger are included from one unread
  range.
- When older messages exist outside the retained 20-message window, the first item in the
  mailbox batch is a system message stating that earlier conversation messages were
  omitted.
- The retained provider messages remain in provider order after the omission notice.
- After successful ingestion, the durable read position advances to the trigger and the
  omitted messages are not ingested by a later trigger.
- A channel or thread with no prior read position applies the same newest-20 behavior to
  its first authorized trigger.

### REQ-6. Concurrent and retry-safe cursor advancement

Concurrent, duplicate, delayed, and failed requests must not lose, reorder, or duplicate
conversation input.

**Acceptance criteria**

- Processing is serialized per connection and parent-channel or thread conversation
  scope.
- Every serialized request rechecks the current durable read position before reading or
  accepting input.
- Input-batch acceptance and read-position advancement succeed together or neither is
  retained.
- A failure during provider history retrieval, conversation or Session resolution,
  mailbox acceptance, or read-position advancement returns failure and preserves the
  prior read position.
- Retrying the same trigger recomputes the range from the preserved durable position.
- A later trigger can recover a previously failed range without a retained raw-event
  record.

### REQ-7. Approval-safe original invocation

Participant approval must preserve and automatically execute the original invocation
even when the shared conversation read position advances during approval.

**Acceptance criteria**

- A pending approval durably retains the original connection, conversation scope,
  trigger message identity, and read-position boundary without retaining the provider
  message body.
- Allow automatically resumes ingestion for the original trigger; the participant does
  not need to send another message.
- If the shared read position has not passed the original trigger, Allow uses the normal
  unread-range ingestion and advances the shared position.
- If the shared read position has passed the original trigger, Allow reads the original
  bounded range from its retained boundary, ingests it into the approved Session, and
  does not move the shared position backward.
- The same provider message may appear in different Session contexts when independent
  invocation and approval boundaries require it.

### REQ-8. Append-only revision scope

Conversation ingestion must remain forward-only and must not create a secondary update
or deletion synchronization path for already-read messages.

**Acceptance criteria**

- Provider edit and delete events at or before the durable read position are discarded by
  the normal position filter.
- Previously accepted Session input is not rewritten or removed after a provider edit or
  deletion.
- A provider-history read uses the provider-visible state returned at the time of that
  unread-range ingestion.

### REQ-9. Equivalent Redis and in-memory conversation locking

Conversation serialization must retain the same product behavior with either the
Redis-backed or in-memory external-channel conversation-lock backend.

**Acceptance criteria**

- External-channel conversation-lock configuration explicitly selects either the
  in-memory or Redis-backed implementation.
- Both implementations use the same conversation scope and admitted-request behavior.
- A Redis-backed lock configuration does not silently switch to process-local locking
  during a Redis outage.
- Redis availability, persistence, retained locks, leader election, or HA is not the
  durable source of conversation correctness.
- A newly empty Redis instance allows new requests to resume from durable conversation
  read positions without restoring prior keys or locks.
- This requirement does not change the existing Session broker or Agent Worker
  deployment dependencies.

### REQ-10. No deferred inbound-event inbox

Normal external-channel message handling must not depend on a durable raw-event inbox or
background polling processor.

**Acceptance criteria**

- Successful message handling reaches durable mailbox acceptance during the admitted
  request rather than waiting for an event claim loop.
- No retained inbound-event row is required to supply message content, preserve ordering,
  retry a failed range, or resume after process restart.
- Provider history and durable read positions provide the recoverable message-ingestion
  boundary.
- Failure is surfaced to the transport so redelivery can occur instead of acknowledging
  a request that has only been queued for later interpretation.

## Fixed Constraints

- Slack and Discord must expose the same user-visible invocation, continuation, context,
  approval, and Session handoff semantics.
- Existing route automatic-access, grant, block, and approval-decision semantics remain
  unchanged; this snapshot changes how authorized conversation input is collected and
  handed off, not who is authorized.
- The provider's visible history is the message-content authority for an ingestion range;
  inbound socket or webhook payload content is not the Session input authority.
- Agent execution remains asynchronous after durable Session input acceptance.
- One authorized trigger produces one ordered mailbox input batch and one Session
  execution trigger.
- The connected provider App or Bot identity is the only author-level exclusion from a
  provider-visible history range.
- The bounded unread-history limit is 20 provider messages.
- PostgreSQL remains the durable source of conversation read progress and accepted
  Session input.
- Redis-backed external-channel conversation locking remains optional and ephemeral; the
  explicitly selected in-memory lock backend preserves equivalent conversation
  semantics.
- Credentials, callback capabilities, raw provider payloads, attachment URLs, and message
  bodies must not be added to logs or operational evidence.

## Open Assumptions

- Slack and Discord expose bounded history reads that can return the participant-visible
  messages through a known trigger identity within their acknowledgement budgets under
  normal operation.
- Provider message identities provide a stable ordering and bounded-pagination boundary
  within each parent channel or thread scope.
- The connected App or Bot identity can be determined reliably for message exclusion.
- Provider messages that are no longer visible or retrievable at ingestion time cannot be
  reconstructed from Azents because no deferred raw-event inbox is retained.

## Confirmation

Confirmed by the requester on 2026-07-29 before ADR and design decisions began. The
requester approved the complete synchronous handoff, provider-history cursor ingestion,
approval-boundary, bounded-context, retry, and Redis/non-Redis behavior in this snapshot.
On 2026-07-29, the requester clarified that the Redis/non-Redis behavior applies to the
external-channel conversation-lock backend only; removing Redis from the existing
Session broker and Agent Worker is outside this snapshot.
