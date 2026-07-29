---
title: "Responsive Context-Preserving External Conversations Phase 3 Transport Cutover Plan"
created: 2026-07-29
updated: 2026-07-29
tags: [external-channel, ingress, slack, discord, cutover]
---

# Phase Execution Plan

- Phase: `3 — Transport Cutover`
- Branch/base:
  `feature/channel-responsive-context-05-transport-cutover` →
  `feature/channel-responsive-context-04-ingestion-core`
- PR boundary: Replace normal Slack HTTP, Slack Socket Mode, and Discord Gateway
  message admission with the shared synchronous ingestion service; eagerly resolve Discord
  delivery threads before acceptance; route authenticated Slack revocation directly; and
  stop Agent Worker legacy event-processor startup while retaining additive legacy schema
  and rollback-readable code for qualification and later contraction.
- Inputs:
  - approved `channel-260729` Requirements, ADR, and Design from PR #1023;
  - multi-phase implementation plan from PR #1024;
  - Phase 1 Foundation position, lock, history, deadline, preflight, and quiesce contracts
    from PR #1026;
  - Phase 2 provider-neutral ingestion, atomic acceptance, typed replay, mailbox, and
    deadline-bounded wake contracts from PR #1027;
  - current Slack HTTP/Socket, Discord Gateway, delivery/provisioning, connection
    lifecycle, worker-composition, selector, shortcut, and interaction implementations;
  - current External Channel living specs and project conventions.
- Deliverables:
  - one transport-facing synchronous handoff boundary that projects authenticated Slack
    and lease-owned Discord create triggers into credential-free ingestion requests;
  - exact Slack HTTP acknowledgement mapping after durable ingestion, including bounded
    absolute deadline propagation and retryable failure surfacing;
  - exact Slack Socket acknowledgement-after-ingestion behavior, with retryable failure
    leaving the envelope unacknowledged and terminating the owned connection;
  - exact Discord Gateway callback behavior in which retryable ingestion failure escapes
    through the controlled reconnect/gap boundary while completed terminal outcomes
    return normally;
  - direct normal create-trigger handling with Slack edit/delete and Discord update/delete
    acknowledged or ignored without creating new Session input;
  - lease/configuration authority projection and final revalidation for every transport;
  - provider-I/O-free Slack thread resolution plus eager Discord root-message thread
    create/reconcile before history and acceptance, all within the original deadline;
  - locator/resource/delivery identities for unbound parent, manual existing thread, and
    bound-thread continuation with no raw inbound message content as history authority;
  - direct authenticated Slack `app_uninstalled` and `tokens_revoked` connection lifecycle
    transition without creating raw event rows;
  - selector, shortcut, and interaction continuation through typed boundaries while
    retaining only rolling compatibility for pre-cutover legacy records;
  - Agent Worker composition without `ExternalChannelEventProcessorService` startup and
    guard coverage proving normal message ingress has exactly one authority;
  - focused acknowledgement, lease-loss, deadline, provisioning, revocation, composition,
    rollback-compatibility, security, and no-dual-ingress tests.
- Non-goals:
  - no destructive removal of legacy event, hydration, pending-context, activation,
    truncation, or source-event schema and no deletion of rollback-readable processor code;
  - no PR #1020 finished-activation recovery or stale-mailbox cleanup removal;
  - no managed binding API, OpenAPI, generated-client, Web, or UI contraction;
  - no deterministic provider-fake expansion, full cutover E2E qualification, evidence
    report, or live provider verification assigned to Phase 4;
  - no living-spec promotion, implemented snapshot date, plan cleanup, deployment,
    Kubernetes mutation, live ingress quiesce, database repair, or PR merge;
  - no compatibility fallback from synchronous normal message ingress to legacy event
    admission after cutover.
- Interfaces:
  - A new transport handoff service accepts only an authenticated transport projection,
    ingress authority, received timestamp, and absolute deadline. It resolves a complete
    `ExternalChannelIngestionRequest` and invokes
    `ExternalChannelConversationIngestionService`; transports do not reproduce history,
    routing, authorization, mailbox, cursor, or wake behavior.
  - Slack HTTP uses configuration authority only with `SLACK_HTTP`; Slack Socket uses the
    current socket lease owner with `SLACK_SOCKET`; Discord Gateway uses current lease
    owner and generation with `DISCORD_GATEWAY_HTTP`; no transport uses durable replay.
  - Each transport creates the absolute deadline at receipt/callback entry and passes the
    same deadline through projection, optional Discord provisioning, provider history,
    final acceptance, broker dispatch, and acknowledgement mapping.
  - Slack HTTP returns provider success only for `accepted`, `duplicate`,
    `awaiting_selection`, `awaiting_access`, `ignored`, or safe terminal rejection.
    `retryable_failure` and unexpected failures propagate as non-success server handling.
  - Slack Socket sends `SocketModeResponse` only after a completed non-retryable ingestion
    outcome. Retryable failure raises a controlled socket error, sends no acknowledgement,
    and lets the manager record a gap/reconnect.
  - Discord Gateway returns from the serialized callback only after a completed
    non-retryable ingestion outcome. Retryable failure raises a controlled Gateway error
    so the manager records a safe gap and reconnects under its existing lease lifecycle.
  - Only create triggers enter synchronous ingestion. Slack edit/delete and Discord
    update/delete do not persist new revisions, batches, mailbox items, or Session input.
  - Slack unbound parent invocations resolve to the native root thread timestamp; manual
    Slack threads reuse their current root. Discord manual threads reuse their channel;
    Discord unbound parent invocations call `DiscordDeliveryClient.ensure_thread` before
    history and acceptance and reject failed or ambiguous unresolved outcomes.
  - Provider thread provisioning is non-retrying beyond the existing one-read,
    one-create, one-reconcile contract. It never runs inside the final DB transaction and
    never stores credentials, provider response bodies, or raw inbound payloads.
  - Direct Slack revocation calls the existing connection lifecycle service only after
    signature and connection identity validation. It commits lifecycle state before HTTP
    or Socket acknowledgement and does not enter conversation ingestion.
  - Normal message paths cannot call `ExternalChannelAdmissionService.admit`,
    `admit_discord_gateway_event`, or the legacy event processor after cutover. Legacy
    access/selector records may retain their existing fallback until contraction.
  - Diagnostics remain content-free and must not log provider/resource/message/connection
    identifiers, credentials, locators, payloads, or message content.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Transport handoff and provider locator projection | `/root` | New narrowly scoped transport-ingestion/resolution module(s) under `python/apps/azents/src/azents/services/external_channel/`; `slack_events.py`, `discord_events.py`, and focused tests only where projection helpers belong | Stable Phase 2 ingestion request/outcome interfaces | Authenticated Slack/Discord create-trigger projection, route/resource/thread resolution, authority/deadline construction, and closed outcome mapping without raw-content authority | Projection/unit tests for parent/manual/bound scope, invocation classification, connected App/Bot exclusion, deadline propagation, malformed/missing identities, and content-free representations; Ruff/Pyright |
| Slack HTTP and direct revocation | `/root` | `services/external_channel/http_admission.py`, Slack HTTP/revocation/connection lifecycle integration, public route mapping only if required, and focused tests | Transport handoff service; signed configuration authority | Direct synchronous message handoff, provider success only after durable terminal result, edit/delete no-input behavior, direct uninstall/token revocation, retained interaction behavior | HTTP acknowledgement/failure/status tests, revocation commit-before-ack tests, signature/configuration fence tests, legacy-admission-not-called guards |
| Slack Socket Mode cutover | `/root` | `services/external_channel/slack_socket.py`, `socket_manager.py`, and focused tests | Transport handoff service; socket lease authority | Ingestion-before-envelope-ack, retryable no-ack/reconnect, direct revocation, interaction handoff preservation, lease/deadline propagation | SDK runner acknowledgement timing, manager lease loss, reconnect/gap, quiesce, revocation, edit/delete, cancellation, and no-legacy-admission tests |
| Discord Gateway and eager thread provisioning | `/root` | `services/external_channel/discord_gateway_manager.py`, `discord_gateway.py`, `discord_events.py`, `discord_delivery.py` only where a bounded provisioning adapter is needed, and focused tests | Transport handoff service; Gateway lease authority; existing `ensure_thread` contract | Serialized synchronous create handoff, eager parent-thread create/reconcile, manual-thread reuse, update/delete no-input behavior, retryable reconnect/gap mapping | Gateway lease-generation, callback failure, provisioning delivered/failed/unknown, parent/manual/bound routing, deadline, cancellation, and no-legacy-event tests |
| Worker composition and cutover authority guards | `/root` | `python/apps/azents/src/azents/worker/worker.py`, worker tests, dependency composition/config/preflight guard tests only where required | All normal transports switched | Agent Worker no longer starts the legacy processor; normal messages have one synchronous authority; rollback-readable processor code and legacy schema remain | Worker task-composition tests, startup/shutdown cancellation tests, dependency graph checks, no dual admission assertions, focused legacy fallback regression tests |
| Independent review | `/root/channel-responsive-reviewer` | Read-only complete Phase 3 diff | Stable integrated diff and validation evidence | Requirements, acknowledgement/deadline, lease/authentication, provider mutation, cutover authority, privacy, recovery, and scope findings | One review report; targeted re-review only for qualifying findings |

- Integration order:
  1. Primary fixes the transport handoff inputs, authority/deadline rules, create-only
     outcome mappings, and provider-neutral locator/resolution result contracts.
  2. Primary implements provider-I/O-free Slack resolution and Discord eager
     `ensure_thread` adaptation outside transactions, including failure classification.
  3. Primary switches Slack HTTP normal messages and direct revocation while preserving
     URL verification and interaction behavior.
  4. Primary switches Slack Socket Mode under current lease ownership and validates
     acknowledgement, retryable reconnect, cancellation, and revocation behavior.
  5. Primary switches Discord Gateway create callbacks under lease generation fencing and
     removes update/delete legacy message admission.
  6. Primary removes Agent Worker event-processor startup, adds one-authority guards, and
     verifies old access/selector fallback remains only for pre-cutover records.
  7. Primary runs focused and combined validation, requests one read-only review from
     `/root/channel-responsive-reviewer`, batches required corrections, and requests
     targeted re-review only for requirements/design, security/data-loss, or material
     convention/interface corrections.
  8. Primary runs final validation on the unchanged integrated diff, records the context
     checkpoint, commits, pushes, and opens PR 5 before beginning Phase 4.
- Independent review:
  - Scope: complete Phase 3 diff against `channel-260729/REQ-1`, `REQ-2`, `REQ-6`,
    `REQ-8`, `REQ-10`, accepted ADR decisions, Design transport/process/deadline/thread/
    cutover sections, current specs, Phase 1/2 contracts, and this PR boundary.
  - Criteria: authentication and lease authority; one absolute deadline; durable
    acceptance and wake before acknowledgement; no acknowledgement on retryable failure;
    eager Discord thread resolution; manual/bound thread reuse; create-only Session input;
    direct revocation; no raw event authority or fallback; one normal ingress authority;
    content-free diagnostics; cancellation and rollback behavior; no destructive
    contraction, public-surface drift, provider-fake expansion, or live mutation.
  - Inputs: authoritative snapshot, multi-phase plan, Phase 1/2 checkpoints, this phase
    plan, stable implementation diff, focused test output, and final validation evidence.
  - Output: grounded Critical/Warning findings with exact paths, or explicit no findings.
- Final validation:
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - focused Slack HTTP route/admission, Slack event projection, connection lifecycle, and
    direct revocation tests
  - focused Slack Socket runner/manager acknowledgement, lease, reconnect, interaction,
    and cancellation tests
  - focused Discord Gateway/manager/event projection/delivery provisioning tests
  - focused transport-ingestion resolution, authority, deadline, outcome, and privacy tests
  - focused Agent Worker composition and legacy access/selector fallback tests
  - affected Phase 2 ingestion/history/store/replay/mailbox regression tests
  - `cd python/apps/azents && uv run pyright`
  - `cd python/apps/azents && uv run pytest`
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - `python -m unittest scripts.tests.test_gen_docs_index`
  - `git diff --check`
- Scope-drift check:
  Compare the final diff with the deliverables and non-goals above. Remove legacy schema,
  migration, hydration/pending-context/activation contraction, PR #1020 cleanup, public
  API/client/Web changes, provider-fake/E2E qualification, living-spec promotion, plan
  cleanup, deployment, infrastructure, or live provider mutation. Do not retain a normal
  message fallback to event admission after switching a transport. Keep processor code
  only as rollback-readable and pre-cutover-record compatibility until Phase 5
  contraction.
- Context checkpoint:
  - `ExternalChannelTransportIngestionService` is the only normal-message handoff for
    Slack HTTP, Slack Socket Mode, and Discord Gateway. It projects authenticated
    transport events into credential-free locators and calls the shared Phase 2 ingestion
    service without retaining raw event rows.
  - Slack HTTP uses configuration authority; Slack Socket uses its current lease owner;
    Discord Gateway uses lease owner plus generation. Every request carries the
    configuration generation and one receipt-derived absolute deadline. Direct Slack
    revocation additionally revalidates configuration generation under the lifecycle row
    lock so an old signed callback cannot mutate a replaced configuration.
  - HTTP returns success only after an acknowledgeable ingestion outcome. Socket Mode
    sends its envelope response only after ingestion and leaves retryable failures
    unacknowledged. Gateway callbacks return only after an acknowledgeable result;
    retryable failures cross the controlled gap/reconnect boundary.
  - Slack root and manual-thread identities require no provider mutation. Discord manual
    and bound threads reuse their authoritative channel identity. An unbound Discord
    invocation validates lease/configuration authority before provider I/O, eagerly calls
    `ensure_thread` outside the final transaction, and passes the confirmed thread into
    final acceptance for a second authority check.
  - Slack edit/delete and Discord update/delete events create no canonical revision,
    mailbox item, or Session input. Signed Slack uninstall/token-revocation callbacks use
    direct connection lifecycle transitions and commit before acknowledgement.
  - Agent Worker no longer composes or starts
    `ExternalChannelEventProcessorService`. Repository and transport guards confirm that
    normal messages cannot call legacy `admit`, `admit_discord_gateway_event`, or event
    processor paths. Legacy processor code and schema remain rollback-readable for
    pre-cutover selector/access records until contraction.
  - Diagnostics remove connection/provider/resource identifiers from changed manager
    exception logs. Locators and request representations remain content-free, and
    credentials stay transient inside validated provider boundaries.
  - Independent review by `/root/channel-responsive-reviewer` reported one Warning:
    retryable Slack Socket ingestion initially unwound through the generic transport-error
    release path. It now records `socket_ingestion_retryable` under the retained lease,
    waits the bounded reconnect delay, and opens a fresh connection without acknowledging
    the failed envelope. Targeted re-review concluded:
    `No remaining Critical/Warning findings.`
  - Final validation on the integrated diff: Ruff format/check passed; Pyright reported
    `0 errors`; transport and regression focused suites passed; the complete backend
    suite reported `3818 passed, 17 warnings`; documentation index validation and its 14
    unit tests passed; and `git diff --check` passed.
  - Remaining Phase 4 scope is deterministic provider-fake and E2E cutover qualification,
    acknowledgement timing evidence, concurrency/duplicate proof across lock backends,
    and the qualification report. This PR does not contract legacy schema/code, alter
    public management surfaces, deploy, mutate live infrastructure, or merge the stack.
