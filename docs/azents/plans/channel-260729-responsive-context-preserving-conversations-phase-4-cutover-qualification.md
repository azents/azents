---
title: "Responsive Context-Preserving External Conversations Phase 4 Cutover Qualification Plan"
created: 2026-07-29
updated: 2026-07-29
tags: [external-channel, e2e, qualification, slack, discord]
---

# Phase Execution Plan

- Phase: `4 — Cutover Qualification`
- Branch/base:
  `feature/channel-responsive-context-06-cutover-qualification` →
  `feature/channel-responsive-context-05-transport-cutover`
- PR boundary: Qualify the synchronous Slack HTTP, Slack Socket Mode, and Discord Gateway
  ingress generation through deterministic provider fakes, public/provider E2E paths,
  lock-backend contracts, and aggregate cutover-preflight evidence while the additive
  legacy schema remains present but has no normal-message runtime owner.
- Inputs:
  - approved `channel-260729` Requirements, ADR, and Design from PR #1023;
  - multi-phase implementation plan from PR #1024;
  - Foundation position/lock/history/deadline/preflight contracts from PR #1026;
  - provider-neutral ingestion, immutable batch, replay, mailbox, and wake contracts from
    PR #1027;
  - synchronous transport cutover, eager Discord provisioning, direct Slack revocation,
    and Worker composition from PR #1028;
  - existing deterministic Slack and Discord provider fakes and External Channel public
    E2E journeys.
- Deliverables:
  - one reusable deterministic qualification helper layer that configures provider
    history and triggers through public/provider paths without direct product DB writes;
  - Slack HTTP evidence that successful callback completion observes an already-durable
    Session/binding input and duplicate delivery creates one logical accepted boundary;
  - Slack Socket evidence that the provider envelope is acknowledged only after the same
    durable boundary and retryable ingestion remains unacknowledged across reconnect;
  - Discord Gateway evidence that message-create completes only after eager thread
    provisioning and durable acceptance, while update/delete create no Session input;
  - mixed-author history evidence retaining humans, other bots, and visible system
    authors while excluding the connected App/Bot;
  - newest-20 plus one omission-reminder evidence for an over-bound provider range;
  - provider-history failure evidence proving the normal conversation position does not
    advance and a later retry accepts the original unread range;
  - duplicate/concurrency evidence converging on one invocation batch, mailbox input, and
    logical wake for both memory and Redis conversation-lock implementations;
  - approval Allow replay evidence before and after shared position advancement without
    cursor/resource hydration regression;
  - create-only evidence proving Slack edit/delete and Discord update/delete do not
    rewrite accepted Session input;
  - content-free provider fake state and cutover preflight pass/blocked evidence with only
    stable categories and aggregate counts;
  - fixes for defects discovered by the deterministic qualification, without destructive
    contraction or public-surface removal.
- Non-goals:
  - no legacy table, column, enum, hydration/activation field, event processor source,
    generated client, or Web removal;
  - no current living-spec promotion or implemented snapshot date;
  - no live Slack/Discord credentials, provider verification, ingress quiesce, deployment,
    Kubernetes mutation, database repair, migration execution, or PR merge;
  - no full post-contraction matrix assigned to PR 8;
  - no evidence output containing provider/resource/connection/session identifiers,
    callback bodies, message content, attachment metadata, credentials, signatures, URLs,
    or authorization headers.
- Interfaces:
  - E2E prepares state only through public management APIs and bounded provider-fake
    controls. Tests do not insert, update, or delete product database rows directly.
  - Slack history pages preserve provider order and range identities in fake memory but
    expose only operation names, counts, acknowledgement IDs/categories, and bounded
    ordering evidence through `__testenv/state`.
  - Discord history/root/thread fixtures remain bounded in fake memory. State output
    exposes only request counts, safe operation categories, Gateway connection/dispatch
    counts, and thread-provisioning outcomes.
  - Public assertions discover created Sessions through Chat list APIs, then read Session
    Channels and Session history through public APIs. They do not infer success only from
    provider delivery.
  - Concurrency barriers are armed and released through provider-fake control endpoints;
    they never retain inbound content or production identifiers in evidence.
  - Preflight tests exercise `ExternalChannelCutoverPreflightService` and the operator CLI
    with aggregate projections only. Blocked output names stable failure categories and
    contains no row identifiers.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan and qualification helpers | `/root` | This plan; focused helpers in `testenv/azents/e2e/src/tests/azents/public/test_external_channels.py` or a narrowly scoped sibling module | Existing public clients and fixture composition | Reusable setup, trigger, Session discovery, transcript, and sanitized provider evidence helpers | Ruff/Pyright; helper-focused tests |
| Slack deterministic qualification | `/root` | `testenv/azents/e2e/src/support/slack_provider_fake.py`, its unit tests, and External Channel E2E | PR #1028 HTTP/Socket cutover | Range-aware mixed history, ordered Socket dispatch/ack evidence, retry/no-ack controls, duplicate/concurrency coverage | Fake unit tests; focused Slack HTTP/Socket E2E |
| Discord deterministic qualification | `/root` | `testenv/azents/e2e/src/support/discord_provider_fake.py`, its unit tests, and External Channel E2E | PR #1028 Gateway/provisioning cutover | Gateway completion, eager thread reuse/create, mixed history, retry and update/delete evidence | Fake unit tests; focused Discord Gateway E2E |
| Lock, cursor, replay, and preflight evidence | `/root` | Focused backend tests and E2E assertions only where missing | Phase 1/2 contracts and transport fixtures | Memory/Redis convergence, failure-position preservation, replay boundaries, aggregate preflight pass/abort | Focused backend contract tests; CLI/preflight tests; deterministic E2E |
| Independent review | `/root/channel-responsive-reviewer` | Read-only complete Phase 4 diff | Stable integrated diff and validation evidence | Contraction-prerequisite, E2E-trustworthiness, privacy, concurrency, cursor, and scope findings | One review report; targeted re-review only for qualifying findings |

- Integration order:
  1. Primary inventories current fake controls and existing journeys, then adds only the
     missing bounded evidence/control fields.
  2. Primary adds fake-unit coverage proving controls are bounded, deterministic, and
     content-free before using them from product E2E.
  3. Primary adds Slack HTTP and Socket synchronous qualification, including durable
     Session discovery, duplicate/no-ack behavior, mixed history, omission, and edit/delete.
  4. Primary adds Discord Gateway qualification for eager parent thread creation,
     manual/bound reuse, retry, and update/delete behavior.
  5. Primary adds or expands memory/Redis duplicate-concurrency, failure-position,
     approval replay, and aggregate preflight tests where E2E cannot observe the exact
     internal invariant through a public surface.
  6. Primary runs focused fake and E2E selections, fixes product or fixture defects, then
     runs deterministic E2E and affected full backend/fake suites.
  7. Primary requests one read-only review from `/root/channel-responsive-reviewer`,
     batches grounded corrections, and requests targeted re-review only for
     requirements/design, security/data-loss, or material interface findings.
  8. Primary records the qualification checkpoint, commits, pushes, and opens PR 6 before
     beginning contraction work.
- Independent review:
  - Scope: complete Phase 4 diff against `channel-260729/REQ-1`, `REQ-2`, `REQ-6`,
    `REQ-8`, `REQ-10`, accepted ADR decisions, Design Test Strategy/cutover/privacy
    sections, prior phase checkpoints, and this PR boundary.
  - Criteria: evidence uses real public/provider paths; acknowledgement assertions are
    causally meaningful; fake controls are bounded and content-free; history order and
    connected-App/Bot exclusion are trustworthy; duplicate/concurrency and failure cursor
    assertions cannot pass vacuously; replay preserves boundaries; preflight output is
    aggregate-only; legacy schema is no longer a normal runtime dependency; no destructive
    contraction, live mutation, or surface drift enters the PR.
  - Output: grounded Critical/Warning findings with exact paths, or explicit no findings.
- Final validation:
  - `cd testenv/azents/e2e && uv run ruff format --check src`
  - `cd testenv/azents/e2e && uv run ruff check src`
  - `cd testenv/azents/e2e && uv run pyright .`
  - focused Slack and Discord provider-fake unit tests
  - focused External Channel deterministic public E2E
  - `cd testenv/azents/e2e && uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src`
  - affected backend lock, ingestion, replay, preflight, and CLI tests
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - `cd python/apps/azents && uv run pytest`
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - `python -m unittest scripts.tests.test_gen_docs_index`
  - `git diff --check`
- Scope-drift check:
  Compare the final diff with the deliverables and non-goals above. Remove schema
  contraction, event/hydration/activation deletion, PR #1020 cleanup, OpenAPI/client/Web
  changes, living-spec promotion, live-provider credentials, infrastructure changes, and
  any direct product DB fixture mutation. Keep fake payload content transient and exclude
  it from evidence, logs, assertion failures, and PR descriptions.
- Context checkpoint:
  Record exact qualified transports and scenarios, fake controls/evidence, public Session
  assertions, memory/Redis contract results, preflight pass/abort categories, commands and
  results, independent review disposition, discovered fixes, remaining PR 7/8 scope, and
  why the additive legacy schema is no longer a runtime correctness dependency before
  opening PR 6.

## Qualification Checkpoint

- Qualified transports:
  - Slack HTTP admission persists canonical provider history and the durable selection or
    access boundary before acknowledgement. Duplicate callbacks converge on one logical
    selector, approval, binding, invocation batch, and public Session input.
  - Slack Socket Mode preserves route ownership while a disabled connection remains
    processable for lifecycle events and exposes no normal-message acknowledgement before
    the synchronous ingestion boundary closes.
  - Discord Gateway uses the configured deterministic REST and Gateway origins, eagerly
    provisions or reuses the delivery thread, and completes message-create only after the
    canonical binding and Session input are durable.
- Public evidence reads logical External Channel input from the Session `/live` mailbox
  projection and `/history` events. It deduplicates the same canonical revision across the
  pending-to-consumed race without direct product database access.
- Provider fakes expose bounded operation, acknowledgement, connection, dispatch, and
  delivery categories only. Their state excludes callback content, canonical message
  bodies, credentials, signatures, authorization headers, and source URLs.
- Discovered defects fixed in this phase:
  - Slack approval persistence now uses provider-authoritative history text and permalink
    data before access replay.
  - Discord SDK REST and Gateway endpoints honor explicit deterministic test origins.
  - Discord canonical history preserves validated source-message URLs.
  - New Multi App selector admissions continue through canonical history before duplicate
    callbacks use the pending-selection shortcut.
  - Full-suite Discord Gateway evidence tolerates other active connection tasks while the
    unique public binding and canonical message assertions retain scenario specificity.
- Contract validation:
  - affected lock, ingestion, replay, preflight, CLI, API, repository, and Gateway tests:
    `113 passed`;
  - provider-fake tests: `43 passed`;
  - final backend suite: `3822 passed`;
  - final deterministic E2E lane:
    `291 passed, 6 skipped, 24 deselected`;
  - backend and E2E Ruff/format/Pyright, documentation index checks, documentation unit
    tests, and `git diff --check`: passed.
- Independent review found no remaining Phase 4 Critical or Warning finding after the
  Multi App selector correction. The retained outbound-control model has no global drain
  for a provider control intent that remains `PENDING` when the HTTP process stops before
  provider I/O. This is not an inbound acceptance or wake correctness dependency and is a
  PR 7 contraction follow-up: extract control delivery from the legacy Event Processor,
  preserve sole-attempt fencing and provider failure settlement, and add bounded recovery
  for pending or interrupted control attempts before removing the processor.
- Remaining scope:
  - PR 7 owns legacy event/hydration/activation contraction, PR #1020 cleanup, UI and
    generated-client work, and the provider-control extraction and recovery above.
  - PR 8 owns the post-contraction validation matrix and final evidence report.
  - PR 9 promotes current specs and the implemented snapshot; PR 10 removes the temporary
    implementation plans.
