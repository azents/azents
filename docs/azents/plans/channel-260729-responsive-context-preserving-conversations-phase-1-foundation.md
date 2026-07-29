---
title: "Responsive Context-Preserving External Conversations Phase 1 Foundation Plan"
created: 2026-07-29
updated: 2026-07-29
tags: [external-channel, foundation, migration, locking, history]
---

# Phase Execution Plan

- Phase: `1 — Foundation`
- Branch/base:
  `feature/channel-responsive-context-03-foundation` →
  `feature/channel-responsive-context-02-implementation-plan`
- PR boundary: Add the rolling-compatible persistence, coordination, provider-history,
  quiesce, and preflight foundation required by synchronous ingestion while the legacy
  event processor remains the only active message-ingestion authority.
- Inputs:
  - approved `channel-260729` Requirements, ADR, and Design from PR #1023;
  - multi-phase implementation plan from PR #1024;
  - read-only persistence, ingress, surface/E2E, and independent-review discovery;
  - current External Channel living specs and project conventions.
- Deliverables:
  - additive conversation-position, immutable boundary, omission, and wake-dispatch
    schema with rolling-compatible legacy defaults;
  - active binding thread-position backfill and fail-fast migration/preflight checks;
  - typed position repository locks and compare/recheck primitives;
  - explicit Redis and in-memory conversation-lock implementations behind one contract;
  - provider position codecs and bounded Slack channel/thread and Discord range readers;
  - absolute deadline and typed provider-history failure contracts;
  - disabled-by-default message-ingress quiesce controls that retain the legacy processor;
  - a content-free cutover preflight service and CLI report;
  - focused model, repository, migration, lock, history, configuration, and preflight
    tests.
- Non-goals:
  - no `ExternalChannelConversationIngestionService` implementation;
  - no mailbox omission reminder or Session wake behavior change;
  - no normal transport handoff to the new history or position path;
  - no legacy event, pending-context, hydration, activation, truncation, or source-event
    removal;
  - no public management API, OpenAPI, generated-client, Web, or E2E journey change;
  - no live ingress quiesce, migration execution, provider call, deployment, database
    repair, or infrastructure mutation.
- Interfaces:
  - `ExternalChannelConversationScopeKind` is a closed parent-channel/thread enum used by
    persistence and lock keys.
  - A position row is owned by one connection and one canonical provider scope; parent
    rows use the provider channel identity and thread rows use channel plus thread
    identity. Provider identifiers remain absent from logs and lock keys.
  - Position boundaries are exclusive start and inclusive trigger strings encoded by
    provider-specific deterministic codecs.
  - Access-request and conversation-admission position/range columns are nullable during
    rolling compatibility; new synchronous writes become mandatory in Phase 2.
  - Legacy invocation batches are backfilled as already dispatched. New wake status is a
    closed pending/claimed/dispatched state with a nullable claim timestamp.
  - `context_omitted` is internal invocation-batch state and never a public managed
    binding field.
  - `ExternalChannelConversationLock` accepts a connection/scope digest and absolute
    deadline, yields ownership that can assert continued validity, and raises typed
    unavailable, timeout, or ownership-lost failures.
  - Redis locks use one random owner token, bounded TTL, renewal, and compare-owner
    release; Redis errors never select memory automatically.
  - Memory locks are process-local keyed `asyncio.Lock` instances with equivalent
    deadline/cancellation semantics.
  - Provider history returns ordered normalized eligible messages, the exact trigger,
    omission presence, range start/trigger positions, and sanitized counts/timing only.
  - Slack history uses `conversations.history` for parent channels and
    `conversations.replies` for threads with `retry_handlers=[]`; no raw Web API or
    generic `.api_call()` is introduced.
  - Discord history preserves current response/item byte limits and adds exact-trigger
    plus bounded-before range behavior.
  - Quiesce controls are disabled by default and reject only normal message ingress;
    connection lifecycle and management remain available.
  - Cutover preflight returns aggregate counts and stable categories only. Any nonzero or
    ambiguous category is an abort result, never a repair action.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Persistence schema and repository | `/root/channel-plan-persistence` | `python/apps/azents/src/azents/rdb/models/external_channel.py`; `python/apps/azents/src/azents/repos/external_channel/{data.py,repository.py}`; generated Alembic revision and `db-schemas/rdb/revision` | Fixed schema and enum interfaces; current migration head | Additive tables/columns/enums/constraints, thread-position backfill, position lock/recheck, wake claim/mark, aggregate preflight repository operations | Model/repository focused tests; Alembic head/history and migration-owned schema contract validation; Ruff/Pyright |
| Lock and provider-history foundation | `/root/channel-plan-ingress` | New external-channel lock/history contract modules; `slack_events.py`, `discord_history.py`, their tests; quiesce checks in Slack HTTP/Socket and Discord Gateway transport services | Fixed scope/deadline/result interfaces; config supplied by primary | Redis/memory lock adapters, position codecs, Slack channel/thread ranges, Discord exact-trigger ranges, disabled quiesce transport handling | Shared lock contract tests; Slack/Discord history and transport-quiesce focused tests; Ruff/Pyright |
| Configuration, preflight service, and integration | `/root` | `python/apps/azents/src/azents/core/config.py`; closed enums shared across workstreams; new preflight application service and CLI; phase plan/checkpoint; shared DI composition and overlapping integration tests | Both owner outputs | Explicit backend/quiesce configuration, content-free preflight command, integrated imports/DI, stable migration chain and final diff | Config/preflight tests; combined focused pytest; full Pyright; docs/diff checks |
| Independent review | `/root/channel-responsive-reviewer` | Read-only complete Phase 1 diff | Integrated stable diff and validation evidence | Requirements, security/privacy, migration/data-loss, lock correctness, provider-boundary, and phase-scope findings | One review report; targeted re-review only for qualifying findings |

- Integration order:
  1. Primary fixes shared enum, configuration, scope, deadline, history-result, and
     preflight-report interfaces without implementing ingestion.
  2. Persistence owner generates the additive migration through `alembic revision`, adds
     models/repository operations, backfill/preflight safety, and focused tests.
  3. Ingress owner implements lock backends, provider codecs/range readers, quiesce
     handling, and focused tests against the fixed contracts without touching
     persistence-owned files.
  4. Primary integrates DI and the content-free preflight service/CLI, resolves only
     shared interface conflicts, and runs combined validation.
  5. Each implementation owner runs focused checks and directly requests read-only review
     from `/root/channel-responsive-reviewer` with its owned diff and validation.
  6. Primary requests the reviewer to assess the stable integrated phase diff. Required
     corrections are batched once, affected checks rerun, and targeted re-review is used
     only for requirements/design, security/data-loss, or material convention/interface
     corrections.
  7. Primary runs final validation on the unchanged integrated diff, records the context
     checkpoint, commits, pushes, and opens PR 3 before Phase 2 begins.
- Independent review:
  - Scope: complete Phase 1 diff against `channel-260729/REQ-3`, `REQ-5`, `REQ-6`,
    `REQ-7`, `REQ-9`, `REQ-10`, ADR-D2/D3, the approved Design foundation/cutover
    sections, current specs, and this phase contract.
  - Criteria: additive and rolling-safe schema; no inferred parent cursor; no accepted
    input loss; deterministic ownership constraints; no transaction held across provider
    I/O; Redis non-authority and no fallback; bounded/deadline-aware provider reads;
    connected-App/Bot exclusion; no content-bearing locator/log/evidence; safe quiesce;
    aggregate-only preflight; no ingress authority switch or destructive contraction.
  - Inputs: authoritative snapshot, multi-phase plan, this phase plan, implementation
    diff, migration revision graph, and focused/final validation results.
  - Output: grounded Critical/Warning findings with exact paths, or explicit no findings.
- Final validation:
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - focused model/repository/mailbox/config/preflight tests selected from changed paths
  - focused Slack/Discord history, lock-contract, and transport-quiesce tests
  - Alembic head/history and revision-pointer validation
  - `cd python/apps/azents && uv run pytest`
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - `python -m unittest scripts.tests.test_gen_docs_index`
  - `git diff --check`
- Scope-drift check:
  Compare the final diff with the deliverables and non-goals above. Move shared ingestion,
  mailbox omission/wake behavior, approval/selector replay, active transport cutover,
  processor removal, contraction, public API/client/Web changes, full E2E, spec promotion,
  and cleanup to their planned later PRs. A small compatibility caller update is allowed
  only when required for the additive model to compile and must preserve legacy behavior.
- Context checkpoint:
  - Migration revision and graph: `acd4e70d9c19`, one linear head after
    `cb091fe69575`.
  - Completed behavior: additive conversation-position/range/omission/wake schema;
    active-binding position backfill with aggregate fail-fast diagnostics; position
    lock/CAS and wake-dispatch repository operations; Redis and memory lock backends;
    bounded Slack/Discord history adapters; disabled-by-default narrow ingress quiesce;
    and aggregate-only cutover preflight service/CLI.
  - Fixed interfaces: exclusive-start/inclusive-trigger positions; credential-free
    Slack/Discord trigger locators with credentials injected only at provider-client
    call boundaries; connected App/Bot exclusion before context bounds; raw provider
    scope validation before normalization; and no Redis-to-memory fallback.
  - Migration tests and CI: all prior ad hoc `src/**/*migration_test.py` files were
    removed. `migration_tests/` is a dedicated `pytest-alembic` PostgreSQL suite that
    validates the revision graph, base-to-head upgrade, bounded roundtrip, Foundation
    DDL, backfill, and fail-fast behavior. The required `ci-python` gate now includes a
    PostgreSQL-backed migration job.
  - Validation evidence: Ruff and format checks passed for the full app; Pyright reported
    `0 errors`; the ordinary app suite passed with `3771 passed`; the migration suite
    passed with `7 passed` through both the local testcontainer path and the exact
    CI-style configured PostgreSQL URL path; documentation index validation and its
    `14` unit tests passed; and `git diff --check` passed.
  - Independent review: the initial Slack lifecycle-quiesce, credential-bearing locator,
    connected-identity pagination, and raw Slack scope-validation findings were fixed.
    Targeted re-review reported no remaining Critical or Warning findings.
  - Scope drift: none. The legacy event processor remains the only active ingestion
    authority; no mailbox/wake cutover, public API/client/Web change, E2E journey,
    contraction, spec promotion, live migration, deployment, or infrastructure mutation
    is included.
  - Phase 2 inputs: the stable position/lock/history/deadline/failure contracts,
    repository primitives, migration head, quiesce controls, and preflight categories.
    Phase 2 must implement the synchronous ingestion transaction and durable mailbox
    wake without changing the Phase 1 compatibility defaults.
  - Context decision: implementation continues with `/root` as the sole implementation
    owner. No implementation subagents continue. `/root/channel-responsive-reviewer`
    may be reused only as the read-only independent reviewer required by the shipping
    workflow.
