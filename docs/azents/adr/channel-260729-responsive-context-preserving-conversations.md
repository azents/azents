---
title: "Responsive Context-Preserving External Conversations"
created: 2026-07-29
tags: [architecture, external-channel, slack, discord, conversation, reliability]
document_role: primary
document_type: adr
snapshot_id: channel-260729
---

# channel-260729/ADR: Responsive Context-Preserving External Conversations

## Context

The confirmed
[channel-260729/REQ](../requirements/channel-260729-responsive-context-preserving-conversations.md)
requires Slack and Discord triggers to resolve their provider conversation, accept one
ordered provider-history batch into the bound Session, and trigger execution before
successful transport acknowledgement. Provider history and a PostgreSQL read position,
rather than a retained inbound event body, are the recovery boundary.

The current message path commits `external_channel_events` from Slack HTTP, Slack Socket
Mode, and Discord Gateway ingress. An Agent Worker later claims those events, projects
canonical messages and revisions, hydrates provider history into
`external_channel_pending_contexts`, activates a waiting binding, creates an invocation
batch and mailbox item, and wakes the Session. This deferred path makes successful
provider acknowledgement mean only that the raw event was queued.

Several current boundaries remain reusable:

- provider HTTP authentication and the fenced Slack Socket and Discord Gateway
  connection managers;
- route, participant access, grant, block, conversation admission, binding, Session,
  invocation-batch, mailbox, and Session-wake domain services;
- provider delivery, Discord thread provisioning, canonical external-message
  projection, and file-transfer contracts; and
- transactional mailbox enqueue, which can participate in the same PostgreSQL
  transaction as external-channel state.

The current resource hydration cursor and binding projection position do not represent
the required read authority. A parent channel needs a position before any binding
exists, while each resolved thread needs its own position after binding. The current
approval flow also depends on retained pending-context revisions and therefore cannot
survive removal of the deferred event inbox without a new immutable provider-history
boundary.

## Decision Backlog

The following are the only hard-to-reverse decisions:

1. **Accepted: synchronous ingestion execution boundary** — all authenticated transports
   directly invoke one shared application service.
2. **Accepted: durable position and serialization authority** — dedicated
   conversation-position rows, a shared Redis or in-memory coordination-lock contract,
   and PostgreSQL compare-and-set protect atomic mailbox acceptance and position
   advancement without holding a transaction across provider I/O.
3. **Accepted: approval replay and inbox cutover boundary** — access requests retain a
   typed immutable provider-history boundary without provider content, Allow reuses the
   shared ingestion service, and the legacy event, hydration, and pending-context path
   is removed through a guarded one-way cutover.

The synchronous handoff, deterministic thread behavior, provider-history authority,
newest-20 bound, connected-App/Bot exclusion, approval outcome, Redis failure policy,
append-only revision scope, and removal of deferred inbound-event processing are fixed
by the Requirements and are not reopened by this backlog.

## Decisions

### channel-260729/ADR-D1 — Authenticated transports directly invoke one shared ingestion service

Slack HTTP, Slack Socket Mode, and Discord Gateway retain their provider-specific
authentication, connection lease, bounded trigger projection, failure signaling, and
acknowledgement responsibilities. After those checks, each transport directly awaits
one provider-neutral conversation-ingestion application service through dependency
injection.

The shared service owns conversation and route resolution, provider-history retrieval,
participant authorization, thread and Session resolution, invocation-batch and mailbox
acceptance, durable read-position advancement, and the execution trigger. It returns a
typed transport-neutral outcome that each ingress maps to its native acknowledgement or
failure behavior.

This decision applies to channel-260729/REQ-1, REQ-3, REQ-6, and REQ-10.

An internal authenticated HTTP relay is rejected because trusted Azents processes would
gain another authentication protocol, payload schema, network deadline, deployment
dependency, and retry identity without changing the application operation. Separate
provider-specific orchestrators are rejected because they would duplicate the
correctness-critical history, authorization, mailbox, cursor, and wake behavior.

### channel-260729/ADR-D2 — PostgreSQL position rows are durable authority behind ephemeral coordination locks

Add one durable conversation-position row for every connection-scoped provider parent
channel or thread. Its provider scope identity is independent from a route, binding, or
AgentSession so a parent channel can advance before a binding exists and each bound
thread can advance independently afterward.

The ingestion service acquires a keyed lock for that exact provider conversation scope.
External-channel configuration explicitly selects either an owner-token-fenced Redis
implementation or the equivalent process-local in-memory implementation. Redis loss or
key eviction does not change the durable read position and does not silently select the
in-memory implementation.

This decision governs external-channel conversation serialization only. It does not
remove or replace the existing Redis-backed Session broker, Agent Worker dispatch, or
unrelated Azents runtime coordination.

Provider history is read while the coordination lock is held but without an open
PostgreSQL transaction. A short transaction then locks the position row and compares
the stored start position with the one used for the provider read. If the position
changed, the fetched result is discarded and the operation restarts from the new
position. Otherwise the transaction creates or reuses the invocation batch and mailbox
item and advances the durable position together. A duplicate or delayed trigger at or
before the current position produces no mailbox input or wake.

This decision applies to channel-260729/REQ-3, REQ-5, REQ-6, and REQ-9.

Storing the position on a resource or binding is rejected because those lifecycles do
not represent the pre-binding parent-channel scope and independent post-binding thread
scope. Holding a PostgreSQL transaction across provider I/O is rejected because
provider latency and rate limiting would retain database locks throughout the
acknowledgement path.

### channel-260729/ADR-D3 — Access requests retain typed replay boundaries through a one-way inbox cutover

An access request retains its existing metadata-only source-message identity and gains
an explicit reference to the durable conversation-position row, the exclusive start
position observed for the original invocation, and the inclusive trigger position. The
request stores no provider message body, normalized revision, attachment URL, or
pending-context projection.

Allow invokes the same conversation-ingestion service with the immutable approval
boundary. If the shared position has not passed the trigger, the service uses the normal
range and advances the shared position. If the shared position is already after the
trigger, the service reads and accepts the original bounded range but does not move the
shared position backward. The access request and invocation-batch identities make a
repeated compatible Allow idempotent.

The synchronous path becomes the only message-ingestion authority. Cutover is guarded
against nonterminal legacy events and waiting hydration work before the event processor
is disabled. The legacy `external_channel_events` and
`external_channel_pending_contexts` tables, resource hydration state, binding activation
hydration fields, and their processor and reconciliation code are then removed. The
canonical external-message, revision, invocation-batch, mailbox, interaction, binding,
work, and delivery models remain where they serve accepted Session input or outbound
product behavior.

This decision applies to channel-260729/REQ-3, REQ-6, REQ-7, and REQ-10.

Encoding the boundary in `decision_policy_snapshot` is rejected because relational
scope and ordering invariants would become untyped and the proposed transition would
permit two ingestion authorities. A smaller deferred invocation job is rejected because
it would recreate an inbound queue whose retry semantics compete with provider
redelivery and the durable conversation position.

## Consequences

- API and ingress-worker processes share one synchronous application service while
  retaining provider-specific transport lifecycles.
- Provider history may be read more than once after a lock loss or position race, but
  PostgreSQL accepts each forward range at most once for a conversation position.
- Parent channels and bound threads gain independent durable read progress that survives
  empty Redis and process replacement.
- Pending approval retains only the immutable provider locator and ordering boundary;
  provider-visible content is fetched when Allow executes.
- Initial binding activation no longer waits for hydration reconciliation. A successful
  ingestion transaction creates or reuses the active binding, invocation batch, mailbox
  item, and wake intent before transport acknowledgement.
- The Agent Worker no longer owns an external-channel event polling loop.

## Risks

- Provider-history reads now consume the provider acknowledgement budget. Adapters need
  strict deadlines, bounded pagination, and deterministic rate-limit and temporary
  failure classification.
- A Redis lease can expire during provider I/O. PostgreSQL position comparison prevents
  duplicate acceptance, but the losing request may repeat provider reads before
  returning.
- The in-memory lock implementation is process-local. Deployment topology should avoid
  independent ingress replicas for the same connection when that backend is selected;
  PostgreSQL comparison still protects durable correctness if this operational
  constraint is violated, but provider reads may duplicate.
- The one-way cutover requires explicit evidence that legacy event and hydration work is
  terminal before old processors stop. A failed precondition must abort the cutover
  rather than discard admitted work.
