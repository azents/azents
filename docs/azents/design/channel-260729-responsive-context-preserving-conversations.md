---
title: "Responsive Context-Preserving External Conversations Design"
created: 2026-07-29
updated: 2026-07-29
tags: [external-channel, slack, discord, backend, reliability, testing]
document_role: primary
document_type: design
snapshot_id: channel-260729
---

# Responsive Context-Preserving External Conversations Design

- Snapshot: `channel-260729`
- Document reference: `channel-260729/DESIGN`
- Requirements:
  [channel-260729/REQ](../requirements/channel-260729-responsive-context-preserving-conversations.md)
- ADR:
  [channel-260729/ADR](../adr/channel-260729-responsive-context-preserving-conversations.md)
- Mode: Collaborative

## Traceability

| Requirement | ADR decisions | Design mechanism |
| --- | --- | --- |
| `channel-260729/REQ-1` | D1-D2 | Shared synchronous ingestion service, bounded transport deadline, atomic mailbox admission, durable Session wake transition, and pre-ack broker dispatch |
| `channel-260729/REQ-2` | D1 | Provider-neutral conversation resolution, eager Discord thread provisioning, immutable binding, and separate parent/thread positions |
| `channel-260729/REQ-3` | D1-D3 | Typed trigger locator, provider-history range adapter, canonical message/revision projection, invocation batch, and position advancement |
| `channel-260729/REQ-4` | D1 | History normalization that excludes only the connected App/Bot identity and preserves the existing provider-visible message payload contract |
| `channel-260729/REQ-5` | D2 | Newest-20 eligible-message collector, one-message omission sentinel, and a leading `system_reminder` in the mailbox batch |
| `channel-260729/REQ-6` | D2 | Redis/memory keyed lock contract, position-row compare-and-set, idempotent batch/mailbox identity, and retryable transport failures |
| `channel-260729/REQ-7` | D1-D3 | Typed immutable access-request boundary and Allow replay through the same ingestion service |
| `channel-260729/REQ-8` | D3 | Create-trigger-only ingestion and provider-history snapshot projection without edit/delete synchronization |
| `channel-260729/REQ-9` | D2 | Explicit Redis or memory lock backend with contract tests and no runtime fallback |
| `channel-260729/REQ-10` | D1, D3 | Direct ingress handoff, guarded cutover preflight, event-processor removal, and schema contraction |

## Current Behavior and Gaps

Slack HTTP, Slack Socket Mode, and Discord Gateway currently project provider callbacks
into `external_channel_events`. The API or ingress worker acknowledges after that row
commits. `ExternalChannelEventProcessorService` later claims rows in an Agent Worker,
normalizes provider content, resolves route and access, hydrates provider history,
stores pending context, activates a waiting binding, creates an invocation batch and
mailbox item, and sends a Session wake-up.

This creates the following gaps:

- successful provider acknowledgement means only that a raw event was queued;
- a shared event claim loop can delay an unrelated conversation;
- resource hydration and event reconciliation must converge before initial activation;
- a parent-channel invocation has no immediate provider-thread and Session handoff;
- access approval depends on retained pending message revisions rather than an immutable
  provider-history boundary;
- the resource hydration cursor and binding projection position do not represent the
  independent parent-channel and thread read scopes; and
- the Session running transition and Redis broker wake happen after the mailbox and
  binding transaction, leaving a crash and retry gap.

The following current components remain valid:

- signed Slack HTTP admission and configuration lookup;
- fenced Slack Socket Mode and Discord Gateway connection ownership;
- provider credential encryption and validated capability snapshots;
- route, default-route, grant, block, access-request, conversation-admission, binding,
  root Session creation, Channel Work, and delivery models;
- Discord root-thread reconciliation and durable resource provisioning;
- canonical external messages, immutable message revisions, invocation batches, and
  mailbox projection;
- the `WAKE_SESSION` mailbox scheduling contract and Session recovery behavior; and
- deterministic Slack HTTP/Socket and Discord REST/Gateway E2E fakes.

## Proposed Architecture

### Transport-neutral trigger locator

Ingress projects each supported provider callback into an
`ExternalChannelTriggerLocator`. The locator contains only:

- provider and transport;
- authenticated connection identity and configuration generation;
- tenant, parent channel, and optional thread identity;
- provider trigger message identity and normalized sortable position;
- provider actor identity;
- whether the callback represents an explicit unbound-conversation invocation or an
  ordinary bound-thread continuation; and
- a lease owner and generation for Socket Mode or Gateway ingress when applicable.

It contains no message body, blocks, embeds, files, attachment URL, raw callback,
interaction token, or credentials. The provider-history copy of the trigger must match
its conversation, provider message identity, position, and actor before it can be
accepted.

Slack `app_mention` supplies the explicit-invocation signal. A normal Slack message in
an already-bound thread supplies a continuation signal. Discord message-create
projection uses the connected Bot mention for an unbound parent or manual thread and
ordinary human messages for a bound thread. Edit, delete, connected-App output, and
unbound non-invocation callbacks finish without creating durable message input.

### Shared synchronous ingestion service

Add `ExternalChannelConversationIngestionService` as the only normal message-ingestion
application boundary. Slack HTTP, Slack Socket Mode, Discord Gateway, selector
completion, and access Allow invoke it directly.

The service accepts:

- the trigger locator;
- ingress authority used to revalidate the signed configuration or current socket lease;
- an absolute transport deadline;
- an optional selected route;
- an optional immutable replay boundary; and
- an operation kind: current trigger, selector continuation, or access Allow.

It returns a typed result:

- `accepted`;
- `duplicate`;
- `awaiting_selection`;
- `awaiting_access`;
- `ignored`;
- `retryable_failure`; or
- `terminal_rejection`.

Transport code maps that result to its native acknowledgement behavior. It does not
reimplement history, access, binding, mailbox, cursor, or wake logic.

### Process integration

Slack HTTP continues to run in the API process. It verifies the signed callback,
projects the locator, invokes the ingestion service, and returns success only for a
completed terminal result.

Slack Socket Mode remains lease-owned by its manager. The envelope acknowledgement is
sent only after the ingestion service returns a completed terminal result. A retryable
failure remains unacknowledged and terminates or reconnects the owned socket through the
existing controlled failure boundary.

The standalone Discord Gateway Worker continues to own discord.py connection lifecycle
and lease fencing. Its serialized callback awaits the ingestion service. A retryable
failure escapes the callback and closes the current client so normal reconnect/Resume
or a later authorized trigger can recover from the unchanged position.

`AgentWorker` stops starting `ExternalChannelEventProcessorService`. Slack Socket Mode
may remain hosted in Agent Worker initially, but it no longer submits work to the Agent
Worker's event loop; it invokes the shared service and uses the process-neutral Session
broker dependency.

Slack connection-revocation callbacks do not enter the conversation-ingestion service.
`app_uninstalled` and `tokens_revoked` invoke the existing connection lifecycle service
directly after transport authentication and commit their lifecycle transition before
acknowledgement. This preserves connection revocation when
`external_channel_events` is removed without retaining a second inbound-event queue.

### Conversation scope and position

Add `external_channel_conversation_positions` with:

- `id`;
- `connection_id`;
- `scope_kind`: `parent_channel` or `thread`;
- `provider_channel_id`;
- nullable `provider_thread_key`;
- nullable `read_through_position`;
- timestamps; and
- partial unique indexes for one parent-channel row and one exact thread row per
  connection.

For Slack, a parent scope is the channel and a thread scope is the channel plus root
thread timestamp. For Discord, a parent scope is the source channel and a thread scope
is the thread channel. Provider positions use the existing Slack padded timestamp
encoding and a fixed-width Discord snowflake encoding so equality and ordering are
deterministic.

The position is independent from route, resource, binding, and Session lifecycle.
Removing a route or disconnecting a binding therefore does not move or delete provider
read progress.

### Conversation-lock contract

Add a narrow `ExternalChannelConversationLock` protocol with an async context manager:

- input: connection and canonical conversation scope;
- input: absolute acquisition/operation deadline;
- result: an owned lease context that can assert continued ownership; and
- failure: typed unavailable, timeout, or ownership-lost exceptions.

The Redis implementation:

- uses a digest of the connection/scope identity in the key rather than raw provider
  identifiers;
- acquires with one random owner token and bounded TTL;
- renews while provider I/O is active;
- releases only through an owner-token comparison script; and
- never falls back to memory after a Redis error.

The memory implementation:

- uses process-local keyed `asyncio.Lock` instances;
- follows the same deadline and cancellation contract; and
- stores no durable state.

Both implementations run through one backend contract test suite. PostgreSQL position
comparison remains authoritative if a Redis lease expires, Redis is emptied, or
independent memory-lock processes overlap.

The lock backend is configured independently from the existing Session broker. Selecting
the in-memory conversation lock does not replace the Redis-backed Session broker, Agent
Worker dispatch, or unrelated runtime coordination in this snapshot.

### Provider-history adapter

Add a provider-neutral `ExternalChannelHistoryAdapter` protocol. Its bounded read
returns:

- normalized eligible messages in provider order;
- the exact normalized trigger;
- whether at least one earlier eligible message was omitted;
- the start and trigger positions used for the read; and
- sanitized timing and count metadata.

The adapter reads the exclusive-start, inclusive-trigger range. It collects at most 21
eligible messages: the newest 20 retained messages plus one omission sentinel.
Connected-App/Bot messages do not count toward that limit. If provider output causes
additional pages to be scanned, the adapter continues only within strict page, byte,
and absolute deadline bounds. It fails rather than claiming a complete range when the
trigger or omission boundary cannot be established.

Slack extends `SlackConversationClient` with one range operation supporting both
channel history and thread replies. It uses the provider's oldest/latest boundary,
filters the exclusive start explicitly, validates the trigger, and returns provider
order rather than API page order.

Discord replaces the hydration-specific root/thread operation with a general channel
range reader. It fetches the exact trigger and bounded messages before it, filters
positions after the durable start, validates channel/thread ownership, and returns
provider order. Existing response and item byte limits remain.

Normalization preserves the current canonical body, attachment metadata, reference
mapping, file locator, author type, provider timestamp, and original-URL contracts.
The exclusion predicate matches only the connected App/Bot identities retained on the
connection. Humans without access, other bots, and provider-visible system authors
remain eligible context.

### Initial conversation resolution

For an unbound parent invocation:

1. Resolve the Single route or active channel default. If Multi selection is required,
   retain only the source identity and immutable position boundary on the conversation
   admission, create the selector intent, and stop with `awaiting_selection`.
2. Create or reuse a metadata-only source-message identity, conversation admission, and
   target resource.
3. For Slack, the root message timestamp is already the provider thread identity.
4. For Discord, create or reuse an `external_channel_resource_provisionings` row and
   call `DiscordDeliveryClient.ensure_thread`. Record the confirmed delivery thread
   before history acceptance. An ambiguous creation is reconciled by reading the root;
   an unresolved outcome fails with the parent position unchanged.
5. Read parent-channel history through the trigger.
6. In the final transaction, create or reuse the active binding and root Session, accept
   the invocation, advance the parent position, and initialize the thread position.

For Slack, the new thread position starts at the root trigger because the root appears
in `conversations.replies` and was already accepted from parent history. For a newly
created Discord thread, the thread position starts empty because the root belongs to the
parent channel. An invocation inside an existing manual thread advances that thread's
position directly and does not create another thread.

Discord Channel Action delivery stops lazily creating a missing thread. A binding
created by this design already has a confirmed delivery channel; a missing target is an
integrity failure.

### Bound-thread continuation

The provider locator first resolves an active resource by its retained delivery-thread
identity and then locks the thread conversation scope.

An ordinary message becomes a trigger only when its provider-history author is a human
participant and the resource has an active binding. Existing grant and block rules
decide whether it is released, rejected, or retained for approval. Messages from other
bots and system authors never trigger by themselves, but a later authorized human
trigger includes them from the same unread range.

Parent-channel messages after a binding exists do not continue that binding. They
remain before the parent position until a later explicit parent invocation establishes
another provider thread.

### Atomic acceptance transaction

Provider I/O occurs without an open database transaction. The final short transaction
uses this lock order:

1. active connection and ingress generation;
2. conversation-position row;
3. selected route and resource;
4. active binding and open conversation admission;
5. access request when Allow is running;
6. Agent and AgentSession lifecycle state; and
7. invocation batch and mailbox identity.

For a normal forward read, the locked position must equal the start position used by
the history adapter. A mismatch rolls back and restarts the read while the coordination
lock is still owned. A trigger at or before the locked position creates no new input.

An accepted transaction:

- persists or reuses canonical principals;
- persists or reuses canonical message identities and immutable history revisions;
- applies those revisions as the accepted provider-visible snapshots;
- creates or reuses the immutable invocation batch and ordered batch items;
- creates or reuses active Channel Work and initial delivery intents;
- creates and links one `EXTERNAL_CHANNEL_INVOCATION` mailbox item;
- records a pending invocation-batch wake dispatch intent;
- marks the AgentSession running for wake-producing input through the existing
  repository method in the same transaction; and
- advances the normal conversation position to the trigger.

The mailbox idempotency key remains `external-channel-invocation:{batch_id}`. The batch
keeps the unique binding/trigger identity and additionally records its conversation
position, range start, trigger position, and `context_omitted` flag.

### Omission system message

Replace hydration truncation counters with one exact `context_omitted` flag on the
invocation batch. The history adapter needs to prove only that at least one earlier
eligible message exists; it does not scan an unbounded range to calculate an exact
omitted count or byte size.

When the flag is true, `build_external_channel_mailbox_payload` prepends one typed
omission item before the external-message items. The mailbox processor promotes it as a
`SYSTEM_REMINDER` with stable bounded text explaining that earlier provider
conversation messages were omitted and only the newest 20 were retained. The following
20 or fewer `EXTERNAL_CHANNEL_MESSAGE` events remain contiguous and in provider order.

### Session wake and acknowledgement

The committed `WAKE_SESSION` mailbox item, AgentSession running transition, and pending
invocation-batch wake dispatch state are the durable execution intent. After commit,
the ingestion service claims that pending state, sends one routing-only `SessionWakeUp`
through a process-neutral broker dependency, and records the batch as dispatched before
returning an acknowledgeable result.

If the process crashes after commit or broker send fails:

- the provider request does not receive a successful acknowledgement when the transport
  supports acknowledgement;
- retry finds the existing invocation batch and mailbox even though the position already
  advanced;
- a pending or stale wake-dispatch claim is reclaimable, so retry marks the Session
  running idempotently and resends the wake without recreating input; and
- existing stuck-Session recovery remains an additional recovery path.

If broker send succeeds but the process fails before recording `dispatched`, retry may
send a duplicate wake. Session mailbox and worker ownership semantics make that routing
signal idempotent. If `dispatched` commits but provider acknowledgement is lost,
redelivery observes the completed dispatch and returns the duplicate terminal result
without another broker send.

### Approval replay

Extend `external_channel_access_requests` with:

- `conversation_position_id`;
- nullable `range_start_position`;
- `trigger_position`; and
- relational checks tying the position, resource connection, and metadata-only source
  message to the request.

`decision_policy_snapshot` remains policy provenance only. It no longer stores
truncation state or provider-history boundary data.

An ungranted trigger creates the access request and approval delivery intent but stores
no message revision or provider content. It does not advance the conversation position.

Allow acquires the same conversation lock and reads the current position:

- when the current position is before the original trigger, it reads after the current
  position through the trigger and advances normally;
- when the current position is already after the trigger, it reads after the retained
  original start through the trigger, accepts the approved invocation, and leaves the
  current position unchanged; and
- when the original invocation batch already exists, it only reasserts the Session wake.

The authenticated Allow decision and grant commit before provider I/O so a retryable
history or broker failure never revokes the participant's durable authorization. A retry
reconstructs the same typed boundary from the committed request. After provider history
is read, binding or Session creation, history projection, batch, mailbox, and normal
position advancement commit in one acceptance transaction, and every locked owner is
revalidated before acceptance.

### Selector and interaction continuation

Extend `external_channel_conversation_admissions` with the same conversation-position,
range-start, and trigger-position boundary. Multi-App selector flows and Discord message
commands retain source identity without retaining content. A selected route invokes the
shared ingestion service with the admission boundary.

`external_channel_interactions` remains because it represents authenticated transient
provider-control lifecycle, not a deferred message-content inbox. `shortcut_source.py`,
`discord_selector.py`, and interaction services stop calling the event processor and
use the trigger/boundary service instead.

The authenticated route selection commits before replay. A retryable replay failure
preserves that selection and retries the same typed admission boundary without retaining
provider content.

### Append-only provider revision behavior

Normal ingestion handles create triggers only. Slack edit/delete callbacks and Discord
message-update/delete callbacks do not persist revisions or invoke Sessions. A later
history read receives the provider-visible state then available for messages after the
position. Messages at or before the position are never reread for edit/delete
synchronization.

Historical revision kinds and lifecycle values remain readable for already accepted
records. New history snapshots use deterministic revision identities without a source
event. `external_channel_message_revisions.source_event_id` and its index are removed.

## Data Model and Public Contract Changes

### Add

- `external_channel_conversation_positions`;
- conversation-position and immutable range columns on access requests and conversation
  admissions;
- conversation-position, range-start, trigger-position, and `context_omitted` fields on
  invocation batches;
- pending, claimed, and dispatched wake state plus claim timing on invocation batches;
  and
- provider-specific position codecs and lock-backend configuration.

### Retain

- connections, routes, defaults, interactions, admissions, resources, principals,
  messages, revisions, bindings, access grants/blocks, invocation batches/items,
  Channel Work, resource provisioning, delivery attempts, and mailbox items where they
  remain part of accepted input or outbound product behavior.

### Remove

- `external_channel_events`;
- `external_channel_pending_contexts`;
- resource hydration status, cursor, watermark, reconciliation boundary, error, and
  timing columns;
- binding activation status, activation trigger, activation wake claim, binding
  projection position, and hydration truncation columns;
- invocation-batch truncation count and size columns;
- event and hydration processor enums that have no remaining owner;
- `ExternalChannelEventProcessorService` and its Agent Worker task; and
- provider event admission methods used only by normal message or shortcut-source
  ingestion.

Connection-revocation callbacks remain supported through direct authenticated
connection lifecycle transitions rather than through retained event rows.

The managed binding API removes `activation_status`, `truncated_message_count`, and
`truncated_size`. Bindings returned through management are either active or
disconnected. Regenerate Python and TypeScript OpenAPI clients and remove the
activation/truncation UI badges and translations.

## Deadline and Failure Handling

Each transport supplies an absolute deadline. The service reserves response time and
passes the remaining budget to lock acquisition, provider history, thread provisioning,
database work, and broker dispatch. It never starts a provider request when the
remaining budget is below that operation's minimum reserve.

Failures are classified narrowly:

- authentication, lease loss, disconnected connection, stale route, block, and invalid
  provider scope;
- lock unavailable, lock timeout, or lock ownership lost;
- provider credentials, permission, resource, rate-limit, temporary, malformed, and
  deadline failures;
- thread provisioning failed or ambiguous;
- history trigger missing, range incomplete, or position codec invalid;
- position compare-and-set retry;
- Session, mailbox, or database failure; and
- broker wake failure after durable acceptance.

Temporary provider, lock, database, and broker failures return retryable transport
failure. Permanent scope, credential, permission, lifecycle, and policy rejections use
the existing provider-health and access-control behavior. No failure logs provider
payloads, message content, attachment metadata or URLs, credentials, raw provider
identifiers, or Session/resource identities.

## Security and Privacy

- Authenticated connection selection remains transport-owned and fail-closed.
- Socket and Gateway lease generation is revalidated before provider requests and final
  acceptance.
- Provider credentials are decrypted only for the current validated connection and are
  never placed in locators, locks, mailbox metadata, or logs.
- Lock keys use bounded digests rather than provider identifiers.
- Pending selector and approval state retains message identity and positions only.
- Provider content first becomes durable when an authorized or approved invocation is
  accepted into its immutable batch.
- File metadata keeps the existing provider-neutral locator contract; private download
  URLs and bytes remain transient.
- Sentry delivery remains logger-integrated; runtime code does not call the Sentry SDK
  directly.

## Migration and One-Way Cutover

Do not modify any executed migration. Use additive and contraction migrations.

### Foundation release

1. Add conversation-position and immutable-boundary schema.
2. Backfill one thread position for each active binding from its projected-through
   position or latest accepted invocation batch.
3. Add repository and migration checks that reject an active binding with no recoverable
   accepted position.
4. Add Redis/memory lock implementations, history range adapters, the shared ingestion
   service, and deterministic tests without wiring normal provider ingress to it.
5. Add temporary configuration gates that can quiesce Slack HTTP, Slack Socket, and
   Discord Gateway message ingress while leaving the legacy event processor running.
6. Add a content-free cutover preflight command.

Parent-channel positions are not inferred from existing per-thread resources. Their
first post-cutover trigger starts with no prior position and therefore applies the
newest-20 rule.

### Cutover preflight

Quiesce message ingress and let ordinary legacy processing converge. Preflight must
report zero:

- accepted, processing, or retryable failed external-channel events;
- waiting-hydration or wake-pending bindings;
- running or incomplete resource hydration;
- pending context rows;
- open conversation admissions;
- pending access requests; and
- pending or attempting resource-provisioning work required by an invocation.

It also verifies that every active binding has an unambiguous resource delivery target,
Session, route, latest accepted batch, and backfilled thread position. The report
contains only aggregate counts and stable failure categories. Any failure aborts the
cutover; no manual database repair is part of this design.

### Ingress switch

Deploy one application generation in which all message transports invoke the shared
service and no process starts the legacy event processor. Re-enable provider ingress
only after API, Agent Worker, Slack Socket, and Discord Gateway instances are on that
generation.

There is no dual-write, dual-read, compatibility processor, or conversion of legacy
event payloads into Session input.

### Contraction release

After the synchronous generation is verified:

1. assert the same legacy-state preconditions in the migration;
2. remove event and pending-context foreign keys and tables;
3. remove hydration and activation columns and unused enums;
4. remove `source_event_id` from message revisions;
5. make new-boundary constraints authoritative for nonterminal admissions and requests;
6. remove temporary quiesce gates and legacy code; and
7. regenerate clients and update the Web management surface.

Rollback before contraction returns to the quiesced legacy generation. After
contraction, rollback means restoring the full prior application and schema from the
deployment backup; no runtime compatibility branch is retained.

## Observability

Add content-free metrics:

- ingestion duration and outcome by provider and transport;
- lock wait, ownership loss, and position compare retry count;
- history request count, scanned count, retained count, and omission flag;
- thread provisioning duration and outcome;
- final transaction duration and rollback category;
- durable-acceptance-to-broker-dispatch duration;
- broker dispatch retry count; and
- acknowledgement-budget exhaustion count.

Structured logs contain provider, transport, scope kind, phase, categorical outcome,
elapsed time, counts, and a request-scoped random trace token. They contain no provider
message, channel, thread, tenant, actor, connection, resource, binding, Session, access
request, attachment, URL, credential, or payload value.

The cutover command reports sanitized aggregates only.

## Living Spec Updates

Update after implementation:

- `docs/azents/spec/flow/external-channel-provider-ingress.md` for direct synchronous
  transport handoff, history range semantics, positions, locks, and event-processor
  removal;
- `docs/azents/spec/flow/external-channel-authorization.md` for immutable approval
  boundaries and Allow replay;
- `docs/azents/spec/flow/external-channel-lifecycle.md` for immediately active bindings
  and removal of hydration activation state;
- `docs/azents/spec/flow/external-channel-delivery.md` for pre-admission Discord thread
  provisioning and removal of lazy thread creation;
- `docs/azents/spec/flow/agent-execution-continuity.md` for the omission reminder and
  contiguous external invocation batch; and
- `docs/azents/spec/flow/test-strategy-e2e-primary.md` for synchronous-ack, cursor,
  approval replay, and lock-backend deterministic scenarios.

`docs/azents/spec/flow/file-exchange-storage.md` requires verification but no intended
semantic change because accepted attachment metadata still receives binding-scoped file
locators at mailbox construction.

## Test Strategy

### E2E primary verification matrix

| Scenario | Slack HTTP | Slack Socket | Discord Gateway |
| --- | --- | --- | --- |
| Authorized unbound parent invocation commits Session input before success acknowledgement/handler completion | Required | Required | Required |
| Provider thread is created or reused and all output targets it | Required | Required | Required |
| Authorized bound-thread continuation needs no mention | Required | Required | Required |
| Manual existing thread is reused for first invocation | Required | Required | Required |
| Other humans, bots, and system authors are context; connected App/Bot is excluded | Required | Required | Required |
| Newest 20 plus leading omission reminder | Required | Required | Required |
| Duplicate and concurrent trigger produces one batch, mailbox, and logical wake | Required | Required | Required |
| Provider/database failure leaves the normal position unchanged | Required | Required | Required |
| Approval Allow replays before and after global position passes the trigger | Required | Required | Required |
| Edit/delete does not rewrite accepted Session input | Required | Required | Required |

### E2E plan and fixtures

Extend the existing deterministic Slack provider fake with bounded
`conversations.history` and range-aware `conversations.replies`. Extend the Discord fake
with exact-trigger plus bounded-before history behavior. Both fakes must support:

- ordered history containing human, connected-App, other-bot, system, file, and
  presentation metadata;
- delayed, rate-limited, malformed, missing-trigger, permission, and temporary failures;
- duplicate delivery and concurrent trigger release;
- acknowledgement timestamps and sanitized request counts; and
- thread existence and creation reconciliation.

The existing external-channel E2E module remains the primary product verification
location. Add deterministic Redis-backed and memory-backed runs for the concurrency
contract. Tests assert durable database state, mailbox/transcript order, provider
acknowledgement timing, sanitized provider evidence, and Session reply destination.

### Service and repository coverage

Add focused tests for:

- trigger locator projection and payload/content exclusion;
- position scope uniqueness and provider position codecs;
- Redis owner-token acquire, renewal, loss, and release;
- memory lock cancellation and deadline behavior;
- shared lock contract with empty Redis during processing;
- history newest-20 collection after connected-App exclusion;
- position compare mismatch retry and duplicate no-op;
- atomic principal/message/revision/batch/mailbox/Session/position commit;
- crash after commit and before broker dispatch;
- repeated wake after accepted cursor advancement;
- typed access-request and selector-boundary replay;
- Discord eager thread provisioning and no lazy delivery creation;
- migration backfill and preflight rejection categories; and
- removal of event, pending-context, hydration, and activation schema.

### Credential and prerequisite snapshot

Deterministic CI uses fake provider credentials, PostgreSQL, and Redis. The memory-lock
contract uses no Redis client. No test evidence contains real credentials, provider
payloads, message bodies, attachment URLs, or production identifiers.

Optional live Slack and Discord verification uses an explicit credential/prerequisite
snapshot that confirms scopes, Guild/channel access, callback reachability, Gateway
intent, and a disposable test conversation. Missing credentials skip only scheduled
optional live verification. When a maintainer explicitly requests a live run, missing
credentials or an unmet prerequisite is a failure.

### CI policy and evidence

Required CI gates:

- Python format, Ruff, Pyright, and targeted/full pytest;
- migration upgrade and preflight integration tests on PostgreSQL;
- Redis/memory lock contract tests;
- generated OpenAPI client checks;
- TypeScript format, lint, typecheck, build, and affected component/story tests; and
- deterministic multiprocess external-channel E2E for Slack HTTP, Slack Socket, and
  Discord Gateway.

Evidence is limited to pass/fail results, categorical outcomes, timings, counts, and
asserted durable identities created by the test fixture.

## Feasibility

| Requirement / decision | Result | Repository evidence and implementation path |
| --- | --- | --- |
| `REQ-1` | feasible | HTTP and Socket acknowledgement already waits for an injected async admission call; Gateway serializes callbacks. Mailbox enqueue and Session running transition can share the final transaction, followed by the existing broker wake. |
| `REQ-2` | feasible | Resources, immutable active bindings, Discord `ensure_thread`, resource provisioning, delivery-channel lookup, and manual-thread detection already exist. Thread creation must move before acceptance. |
| `REQ-3` | feasible | Slack and Discord history adapters, normalized messages, canonical message/revision rows, invocation batches, and mailbox projection exist. They require bounded range APIs and the new position owner. |
| `REQ-4` | feasible | Current normalized bodies, blocks/embeds, files, references, principals, and model-visible rendering are reusable. The author filter must narrow from author class to exact connected App/Bot identity. |
| `REQ-5` | feasible | Provider page limits support bounded collection, and one mailbox item already promotes contiguous external events. The processor can prepend an existing typed `SYSTEM_REMINDER`. |
| `REQ-6` | feasible | PostgreSQL row locks, idempotent inserts, unique batch/mailbox keys, and transaction-scoped enqueue already exist. The Redis/memory lock protocol is new but follows established dual-backend contract-test patterns. |
| `REQ-7` | feasible | Access requests, grants, decisions, source message identities, root Session creation, and Allow transaction already exist. Pending-context release is replaced by typed boundary fetch and the shared acceptance transaction. |
| `REQ-8` | feasible | Edit/delete are isolated to event normalization and revision application. Removing those trigger paths leaves accepted mailbox events immutable while later history reads use current provider state. |
| `REQ-9` | feasible | Redis client infrastructure and in-memory keyed-lock patterns exist. Explicit backend selection can be isolated to the new conversation-lock dependency, while PostgreSQL comparison prevents duplicate accepted input across independent memory-lock processes. Existing Session broker and Worker dependencies remain outside this requirement. |
| `REQ-10` | conditional | Event admission and processing are concentrated in identifiable services and one Agent Worker task. Safe removal requires the designed quiesce release and zero-backlog preflight; without that operational precondition cutover must abort. |
| `ADR-D1` | feasible | API, Agent Worker, and Discord Gateway Worker all use the same dependency container and can resolve one shared service. |
| `ADR-D2` | feasible | Resource/binding positions can be backfilled for active threads, while a new table owns parent and future thread scopes. Mailbox enqueue already accepts the caller's `AsyncSession`. |
| `ADR-D3` | conditional | New requests and admissions can store exact typed boundaries. Legacy pending requests and open admissions cannot be reconstructed exactly, so preflight must require them to resolve or expire before cutover. |

No design blocker remains. The REQ-10 and ADR-D3 conditional results are rollout
preconditions: failure to quiesce or reach zero legacy work aborts deployment without
changing product state.

## Remaining Non-Blocking Risks

- Provider latency can exhaust the acknowledgement budget. The correct result is a
  retryable failure with no normal position advancement.
- A large run of connected-App messages may require more provider pages to collect 21
  eligible messages. Strict page and deadline bounds may fail the trigger rather than
  return incomplete context.
- Provider-deleted or no-longer-visible messages cannot be reconstructed.
- Process-local memory locks permit duplicate provider reads across replicas, but
  PostgreSQL comparison preserves accepted-input correctness.
- Removing managed-binding activation and truncation fields is a generated-client and
  Web contract change that must ship with its consumers.
- The cutover temporarily rejects provider ingress while legacy work drains. Providers
  may retry during this bounded window.

## Delivery Shape

This is a multi-release feature:

1. additive position, boundary, lock, adapter, preflight, and quiesce foundation;
2. complete shared ingestion and approval/selector behavior while still dark;
3. coordinated ingress quiesce, zero-backlog validation, and synchronous-path cutover;
4. deterministic E2E evidence and production validation; and
5. contraction migration, generated-client/Web cleanup, living-spec updates, and
   temporary-gate removal.

Implementation should use phased PRs because the schema foundation must be deployable
before the non-overlapping ingress cutover and the destructive contraction must follow
verified synchronous operation.
