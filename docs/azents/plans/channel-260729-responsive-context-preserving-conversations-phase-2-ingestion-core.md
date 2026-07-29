---
title: "Responsive Context-Preserving External Conversations Phase 2 Ingestion Core Plan"
created: 2026-07-29
updated: 2026-07-29
tags: [external-channel, ingestion, mailbox, session, wake]
---

# Phase Execution Plan

- Phase: `2 — Ingestion Core`
- Branch/base:
  `feature/channel-responsive-context-04-ingestion-core` →
  `feature/channel-responsive-context-03-foundation`
- PR boundary: Add the provider-neutral synchronous conversation-ingestion application
  boundary, its short atomic acceptance transaction, durable mailbox/wake dispatch, and
  immutable selector/access replay while every normal Slack and Discord transport keeps
  using the legacy event processor until Phase 3.
- Inputs:
  - approved `channel-260729` Requirements, ADR, and Design from PR #1023;
  - multi-phase implementation plan from PR #1024;
  - Phase 1 Foundation position, range, lock, history, deadline, preflight, and wake-state
    contracts from PR #1026;
  - current canonical message, access, selector, Channel Work, mailbox, root-Session, and
    Session lifecycle implementations;
  - current External Channel living specs and project conventions.
- Deliverables:
  - credential-free provider-neutral trigger locator, ingress authority, operation kind,
    immutable replay boundary, and closed terminal ingestion outcome contracts;
  - shared initial parent/manual-thread resolution and bound-thread continuation without
    activating any provider transport caller;
  - canonical principal, message identity, and immutable revision persistence derived
    only from provider-history results, never inbound event content;
  - a short atomic acceptance transaction that revalidates ingress and position, creates
    or reuses the route/resource/binding/root Session, invocation batch/items, omission
    state, Channel Work and initial delivery intents, mailbox item, Session-running
    transition, wake intent, and position advancement;
  - deterministic position-mismatch restart and already-advanced/duplicate handling while
    the conversation lock remains owned;
  - one leading typed omission `SYSTEM_REMINDER` followed by at most 20 contiguous
    provider-message events in provider order;
  - pending/stale wake claim, routing-only broker dispatch, dispatched marking, retry,
    ambiguous-send idempotency, and existing-batch wake recovery;
  - access Allow and selector completion replay through the shared ingestion boundary
    using retained typed boundaries, with no provider content retention and no cursor
    rollback;
  - focused rollback, concurrency, replay, mailbox, wake, recovery, security, and dark-path
    tests.
- Non-goals:
  - no Slack HTTP, Slack Socket Mode, or Discord Gateway normal-message transport handoff
    to the new ingestion service;
  - no provider acknowledgement behavior change;
  - no `ExternalChannelEventProcessorService` removal or worker-composition change;
  - no Slack revocation, Discord thread-provisioning cutover, or delivery-target
    contraction assigned to Phase 3;
  - no legacy event, hydration, pending-context, activation, truncation, schema, enum, or
    column removal;
  - no public management API, OpenAPI, generated-client, Web, fixture, or E2E journey
    change;
  - no current-spec promotion, cleanup, live ingress quiesce, provider mutation,
    deployment, database repair, or infrastructure mutation.
- Interfaces:
  - `ExternalChannelConversationIngestionService` is the only new application boundary
    for current-trigger, selector-continuation, and access-Allow operations, but it has no
    normal transport callers in this phase.
  - A trigger locator contains only connection and canonical provider identity/position
    metadata required to fetch history. It contains no message body, attachment content,
    credentials, secret, or raw inbound envelope and has a content-free representation.
  - Ingress authority is typed metadata sufficient to revalidate the active signed HTTP
    configuration or current socket/gateway lease generation in the final transaction;
    it is not provider content or a credential carrier.
  - The closed ingestion outcomes are `accepted`, `duplicate`, `awaiting_selection`,
    `awaiting_access`, `ignored`, `retryable_failure`, and `terminal_rejection`, with
    sanitized reason categories only.
  - The immutable replay boundary identifies the retained conversation-position row,
    nullable exclusive range start, inclusive trigger position, metadata-only source
    message, and resource/connection ownership. It carries no provider content.
  - Provider I/O, including history and any initial Discord provisioning operation that
    is reusable without transport cutover, occurs without an open database transaction.
    The final transaction is short and follows the Design lock order.
  - Normal forward acceptance requires the locked position to equal the history range
    start. A mismatch rolls back all acceptance writes and restarts provider history
    while the conversation lock remains owned. A trigger at or before the current
    position creates no new input.
  - Approval replay before the original trigger advances from the current position.
    Replay after the shared position passes the trigger rereads the retained original
    boundary, accepts the immutable trigger batch, and leaves the shared position
    unchanged.
  - Authenticated Allow and route-selection decisions commit before replay. Retryable
    provider-history or wake failure preserves the committed decision and retries the
    same typed boundary without undoing authorization or retaining provider content.
  - Canonical messages and revisions are persisted only from normalized history-adapter
    output. Inbound transport payloads may identify a trigger but are never content
    authority and are not copied into admissions, access requests, locators, logs, or
    operational evidence.
  - An invocation batch owns one immutable provider-ordered revision set, typed
    conversation/range/trigger positions, `context_omitted`, one linked idempotent
    mailbox item, and a pending/claimed/dispatched routing-wake state.
  - The mailbox idempotency key remains
    `external-channel-invocation:{batch_id}`. When omission is true, sequence zero is one
    bounded stable `SYSTEM_REMINDER`; all following entries are at most 20
    `EXTERNAL_CHANNEL_MESSAGE` events in provider order.
  - Session running state is marked through the existing repository operation inside the
    acceptance transaction. Broker send occurs only after commit through the existing
    process-neutral Session broker dependency.
  - A pending or stale claimed wake is reclaimable. Broker failure resets or leaves a
    recoverable state; an ambiguous successful send may be repeated; a dispatched batch
    is a duplicate terminal result and does not send again.
  - Repository and service diagnostics remain aggregate/content-free and never expose
    provider/resource identifiers, connections, secrets, locators, or message content.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Ingestion contracts and orchestration | `/root` | New modules under `python/apps/azents/src/azents/services/external_channel/` for ingestion contracts/service and focused tests; `deps.py` only when shared DI is required | Phase 1 conversation lock/history/deadline contracts | Typed locator, authority, replay boundary, outcomes, resolution flow, mismatch retry loop, and dark-path service composition | Contract/unit tests; retry/duplicate/delayed/concurrent tests; Ruff/Pyright |
| Atomic persistence and projection | `/root` | `python/apps/azents/src/azents/repos/external_channel/{data.py,repository.py}`; canonical message/resource/binding/Session integration through existing repositories; focused repository tests | Fixed ingestion and replay interfaces | Transaction-scoped ownership revalidation, canonical history persistence, invocation batch/items, Channel Work/delivery intents, mailbox link, running transition, wake intent, and safe position advancement | PostgreSQL-focused rollback/CAS/idempotency tests; projection-query tests; Ruff/Pyright |
| Mailbox omission and wake dispatch | `/root` | `python/apps/azents/src/azents/services/mailbox.py`; mailbox payload/processor tests; new or shared external-channel wake-dispatch service and tests | Stable batch projection and wake repository operations | One omission reminder plus bounded contiguous messages; post-commit pending/claimed/dispatched Session wake with crash/retry behavior | Mailbox ordering/promotion tests; wake failure-window and stuck-Session recovery tests; Ruff/Pyright |
| Approval and selector replay | `/root` | `python/apps/azents/src/azents/services/external_channel/{access.py,selector.py,interaction.py,discord_selector.py}` only where required; focused tests | Stable shared ingestion/replay boundary | Durable authenticated decisions followed by immutable Allow and selected-route continuation before/after cursor advancement without retained provider content | Approval/selector replay, retry-after-decision, and cursor non-regression tests; existing interaction/selector regression tests |
| Independent review | `/root/channel-responsive-reviewer` | Read-only complete Phase 2 diff | Stable integrated diff and validation evidence | Requirements, transaction/idempotency, security/privacy, mailbox/wake, replay, and phase-scope findings | One review report; targeted re-review only for qualifying findings |

- Integration order:
  1. Primary defines the locator, authority, operation, replay-boundary, normalized-history,
     and terminal-outcome contracts plus content-free representations and unit tests.
  2. Primary implements repository projection/acceptance primitives and transaction tests
     using existing Foundation position and wake operations without opening provider I/O
     inside a database transaction.
  3. Primary implements the ingestion resolution/retry loop and canonical-history
     persistence, then integrates binding/root-Session/Channel Work/initial-delivery
     creation through existing services or narrowly extracted shared primitives.
  4. Primary updates the invocation projection and mailbox builder/processor coherently,
     then implements post-commit wake dispatch and failure-window recovery.
  5. Primary routes access Allow and selector completion through immutable replay
     boundaries while leaving normal provider transports and the legacy processor
     unchanged.
  6. Primary runs focused and combined validation, requests one read-only review from
     `/root/channel-responsive-reviewer`, batches required corrections, and requests
     targeted re-review only for requirements/design, security/data-loss, or material
     convention/interface corrections.
  7. Primary runs final validation on the unchanged integrated diff, records the context
     checkpoint, commits, pushes, and opens PR 4 before beginning Phase 3.
- Independent review:
  - Scope: complete Phase 2 diff against `channel-260729/REQ-1` through `REQ-10`, the
    accepted ADR decisions, the approved Design ingestion/transaction/mailbox/wake/replay
    sections, current specs, Foundation contracts, and this phase boundary.
  - Criteria: exact-trigger bounded history; provider I/O outside transactions; lock
    ownership and authoritative PostgreSQL recheck; complete rollback on mismatch;
    canonical-history-only content authority; relational ownership; batch/mailbox/wake
    atomicity and idempotency; one bounded omission reminder; no cursor rollback;
    content-free locator/log/evidence; no raw inbox resurrection; no transport authority
    switch, processor removal, destructive contraction, or public surface change.
  - Inputs: authoritative snapshot, multi-phase plan, Phase 1 checkpoint, this phase plan,
    stable implementation diff, focused test output, and final validation evidence.
  - Output: grounded Critical/Warning findings with exact paths, or explicit no findings.
- Final validation:
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - focused ingestion contract/orchestration and repository transaction tests
  - focused mailbox payload/promotion and wake-dispatch failure-window tests
  - focused access, selector, interaction, and Discord selector replay tests
  - affected legacy event-processor, Session lifecycle, and External Channel regression
    tests proving the new path remains dark
  - `cd python/apps/azents && uv run pyright`
  - `cd python/apps/azents && uv run pytest`
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - `python -m unittest scripts.tests.test_gen_docs_index`
  - `git diff --check`
- Scope-drift check:
  Compare the final diff with the deliverables and non-goals above. Remove active Slack
  HTTP/Socket or Discord Gateway service calls, acknowledgement changes, event-processor
  or worker removal, eager Discord transport provisioning cutover, legacy contraction,
  public API/client/Web changes, provider-fake/E2E expansion, living-spec promotion, and
  cleanup. Additive shared helpers are allowed only when required by the dark ingestion
  path and must preserve every current caller's behavior.
- Context checkpoint:
  - Final contracts:
    `ExternalChannelConversationIngestionService`,
    `ExternalChannelTriggerLocator`, `ExternalChannelIngressAuthority`,
    `ExternalChannelReplayBoundary`, `ExternalChannelCanonicalHistoryMessage`,
    `ExternalChannelIngestionOutcome`, `ExternalChannelProviderHistoryReader`,
    `ExternalChannelDatabaseIngestionStore`, and
    `ExternalChannelInvocationWakeDispatcher`.
  - Current-trigger preparation creates or reuses the parent/manual-thread metadata
    resource and admission from a transport-resolved locator; bound-thread continuation
    reuses the active binding. Provider-side Discord thread creation and normal transport
    locator projection remain Phase 3.
  - Final acceptance revalidates connection authority, conversation position, replay
    resource/source ownership, and route/binding ownership before persisting canonical
    history, binding/root Session, invocation batch/items, Channel Work, initial delivery
    intents, one linked mailbox item, Session-running state, wake intent, and position.
  - Replay after a later shared position accepts the retained original trigger boundary
    while preserving the shared position and resource hydration cursor/high watermark.
    Authenticated Allow and route-selection decisions remain durable across retryable
    replay failure and retry the same typed boundary without retained provider content.
  - Mailbox projection prepends exactly one typed `SYSTEM_REMINDER` when
    `context_omitted` is true, followed by at most 20 contiguous
    `EXTERNAL_CHANNEL_MESSAGE` events.
  - Wake dispatch claims pending or stale state, marks the Session running, bounds broker
    send by the original absolute ingestion deadline, resets the claim on controlled
    failure or timeout, and tolerates ambiguous duplicate routing wakes.
  - Authority validation permits configuration authority only for Slack HTTP, lease
    authority only for Slack Socket or Discord Gateway, and lease-independent durable
    replay for any current connection ingress profile. The final transaction repeats the
    kind/profile and lease-generation fence.
  - Independent review by `/root/channel-responsive-reviewer` reported three Warnings:
    missing broker deadline, missing authority kind/profile fencing, and replay atomicity
    against an older Design sentence. The first two were fixed and covered by focused
    regression tests. The Design and this plan now record the requester-confirmed durable
    decision-before-replay contract. Targeted re-review concluded:
    `No remaining Critical/Warning findings.`
  - Final validation on the integrated Python diff:
    Ruff format/check passed; Pyright reported `0 errors`; the focused Phase 2 and legacy
    regression suite reported `156 passed`; the complete backend suite reported
    `3796 passed, 17 warnings`; documentation index check and its 14 unit tests passed;
    and `git diff --check` passed.
  - Remaining Phase 3 scope: activate Slack HTTP/Socket and Discord Gateway transport
    callers, enforce provider acknowledgement mappings and cutover gates, eagerly
    reconcile Discord threads, route direct Slack revocation, and remove legacy processor
    startup without performing Phase 4 qualification or later contraction.
  - Rolling compatibility: normal provider ingress remains owned by the legacy event
    processor in this PR; existing pending context and legacy requests/admissions retain
    their fallback paths; no schema or public API is removed.
