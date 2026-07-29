---
title: "Responsive Context-Preserving External Conversations Phase 6 Final Validation Plan"
created: 2026-07-29
updated: 2026-07-29
tags: [external-channel, validation, e2e, concurrency, testenv]
---

# Phase Execution Plan

- Phase: `6 — Final Validation`
- Branch/base:
  `feature/channel-responsive-context-08-validation` →
  `feature/channel-responsive-context-07-contraction-surfaces`
- PR boundary: Validate the complete post-contraction Slack HTTP, Slack Socket Mode, and
  Discord Gateway behavior; record sanitized deterministic evidence and fixture
  prerequisites in a supporting Design validation report; compare the implementation
  strictly with the current living specs; and fix only defects discovered by this
  validation.
- Inputs:
  - approved `channel-260729` Requirements, accepted ADR, and primary Design from
    PR #1023;
  - multi-phase implementation plan from PR #1024;
  - additive position, boundary, wake, lock, and provider-history foundation from
    PR #1026;
  - provider-neutral synchronous ingestion from PR #1027;
  - Slack HTTP, Slack Socket Mode, and Discord Gateway transport cutover from PR #1028;
  - deterministic cutover qualification from PR #1029;
  - guarded legacy contraction, provider-control extraction, generated-client
    contraction, and Session Channels cleanup from PR #1030.
- Deliverables:
  - complete deterministic cross-transport evidence for the primary E2E matrix after
    legacy event, hydration, activation, and pending-context removal;
  - explicit Redis-backed and in-memory conversation-lock evidence proving equivalent
    accepted-input semantics without changing Redis broker or lock-failure behavior;
  - provider-fake evidence covering history ranges, author filtering, omission,
    acknowledgement timing, duplicate/concurrent admission, replay, and bounded
    aggregate request counts;
  - a supporting validation report under `docs/azents/design/` recording exact commands,
    environment, fixture/prerequisite state, results, failures, fixes, blocked lanes,
    sanitized evidence, and the current-spec comparison;
  - an exhaustive comparison of the implemented behavior with every listed current spec,
    with all required PR 9 updates identified but not applied;
  - fixes for implementation or deterministic-fixture defects discovered during
    validation, followed by reruns of every invalidated evidence lane;
  - one independent read-only review of the complete Phase 6 diff and evidence.
- Non-goals:
  - no living-spec edits, `last_verified_at` updates, or Requirements/Design
    `implemented` dates; PR 9 owns spec promotion;
  - no accepted ADR edits;
  - no implementation-plan removal; PR 10 owns cleanup;
  - no new product behavior, API redesign, compatibility fallback, legacy hydration or
    processor restoration, or generated-client hand edit;
  - no raw callback, provider message content, attachment data, credentials,
    authorization headers, signatures, production identifiers, or unbounded request
    traces in reports, logs, fixtures, or CLI output;
  - no live provider mutation, database migration, deployment, Kubernetes change,
    ingress quiesce, production preflight, operational-checkpoint claim, PR merge, or
    self-approval.
- Interfaces:
  - provider history is the canonical content source. Typed trigger locators and replay
    inputs contain provider identity and ordering authority only, never raw callback
    content.
  - durable admission commits invocation batch, mailbox input, conversation position,
    wake intent, and initial progress-control intent before provider acknowledgement.
    Provider I/O remains outside final database transactions.
  - PostgreSQL conversation positions are the durable ordering authority. Redis and
    memory locks are equivalent ephemeral coordination implementations. Redis remains
    optional, and Redis lock failure is surfaced rather than silently replaced with an
    in-memory lock.
  - provider-control claim, I/O, and final settlement remain separate boundaries. Final
    settlement locks and revalidates current authority and the same delivery attempt.
  - Slack HTTP, Slack Socket Mode, and Discord Gateway normal messages use typed
    synchronous ingestion. Authenticated lifecycle, revocation, and interaction control
    remain directly processable.
  - acknowledgement results describe durable acceptance, duplicate, denied, retryable,
    and permanent transport outcomes without persisting provider content.
  - diagnostic and evidence outputs are aggregate and content-free. Optional live
    verification consumes a prepared prerequisite snapshot and never runs credential
    discovery inside E2E tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan and evidence inventory | `/root` | This plan; implementation plan; primary Design test strategy; existing Phase 4/5 checkpoints | PR #1030 branch state and CI | Fixed command, matrix, evidence, prerequisite, and sanitization inventory | Plan completeness and scope-drift review |
| Deterministic provider and transport matrix | `/root` | `testenv/azents/e2e/src/tests/azents/public/test_external_channels.py`; provider fakes/proxies and support tests only when a discovered gap requires them | Contracted synchronous ingestion and provider-control paths | Slack HTTP, Slack Socket, and Discord Gateway post-contraction coverage with bounded aggregate evidence | Deterministic E2E lane, focused provider-fake tests, test collection |
| Lock, transaction, and failure matrix | `/root` | External-channel backend tests and owning implementation paths only for discovered defects | PostgreSQL position, wake, delivery-attempt, Redis, and memory-lock contracts | Redis/memory equivalence, duplicate/concurrency, acknowledgement, replay, provider/database/broker failure evidence | Focused backend tests, whole backend suite, Redis-backed E2E |
| Fixture and prerequisite qualification | `/root` | Existing testenv fixture/prerequisite configuration and support; no direct product DB writes | Deterministic fake credentials, PostgreSQL, Redis, memory-lock lane | Exact ready/blocked prerequisite state and sanitized reason codes | Fixture doctor/prerequisite commands where applicable; E2E startup evidence |
| Current-spec comparison and report | `/root` | `docs/azents/design/channel-260729-responsive-context-preserving-conversations-validation-report-2026-07-29.md`; listed current specs read-only | Stable implementation and completed validation evidence | Traceable implementation/spec delta list for PR 9 with no spec edits | File/path/symbol comparison, documentation validation |
| Independent review | `/root/channel-responsive-reviewer` | Read-only complete Phase 6 diff and report | Integrated stable diff and completed evidence | Correctness, security, evidence-integrity, spec-delta, and scope findings | One review report; targeted re-review only for qualifying findings |

- Integration order:
  1. Primary inventories the Design test strategy, existing deterministic E2E/provider
     fake coverage, backend concurrency/failure tests, and the listed living specs.
  2. Primary maps every required matrix cell to an executable test and identifies only
     concrete missing assertions or fixture prerequisites.
  3. Primary runs environment and fixture readiness checks, recording unavailable
     substrates as blocked rather than passed or product-level skipped.
  4. Primary executes provider-fake, focused backend, memory-lock, Redis-lock, and
     cross-transport E2E lanes. Evidence records aggregate counts, result categories,
     test identifiers, and sanitized reason codes only.
  5. Primary fixes discovered implementation or deterministic-fixture defects in their
     owning paths and reruns the focused lane plus every invalidated integrated lane.
  6. Primary runs whole-project Python quality and backend tests. TypeScript checks run
     only if a discovered fix changes TypeScript or generated surfaces.
  7. Primary compares the stable implementation strictly with the seven named current
     specs and verifies whether `file-exchange-storage.md` needs a PR 9 update.
  8. Primary writes the supporting validation report with commands, environment,
     prerequisites, results, failures/fixes, blocked lanes, matrix coverage, sanitized
     evidence, and exact deferred spec updates.
  9. Primary requests read-only review from `/root/channel-responsive-reviewer`, batches
     grounded corrections, and requests targeted re-review only for requirements/design,
     security/data-loss, evidence integrity, or material interface findings.
  10. Primary records the Phase 6 checkpoint, commits, pushes, and opens PR 8 before
      beginning spec promotion.
- Independent review:
  - Scope: the complete Phase 6 diff against the approved Requirements, accepted ADR,
    primary Design test strategy, implementation-plan PR 8 matrix, PR #1030 contracted
    state, and the listed current specs.
  - Criteria: every claimed matrix result is backed by an executed command or is honestly
    marked blocked; Redis and memory coordination preserve the same durable semantics;
    acknowledgement follows durable admission; provider content and credentials never
    enter durable triggers or evidence; provider I/O and final settlement boundaries
    remain safe; spec deltas are complete and deferred; fixes do not introduce new
    behavior, compatibility paths, live mutations, or later-phase work.
  - Inputs: stable branch diff, exact command results, sanitized validation report,
    fixture/prerequisite summary, and implementation-to-spec comparison.
  - Output: grounded Critical/Warning findings with exact paths, or explicit no findings.
- Final validation:
  - environment versions and availability for Python, uv, Node.js, pnpm, Docker,
    PostgreSQL/Testcontainers, Redis, and browser/provider fixtures;
  - deterministic provider-fake unit/support tests covering bounded range requests,
    authors, omission, failures, and content-free evidence;
  - focused backend external-channel repository, ingestion, history, replay, admission,
    transport, lock, provider-control, delivery, interaction, access, and lifecycle tests;
  - explicit in-memory lock contract tests with no Redis client;
  - explicit Redis-backed lock/concurrency tests with a reachable Redis substrate;
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - `cd python/apps/azents && uv run pytest`
  - `cd testenv/azents/e2e && uv run ruff format --check src`
  - `cd testenv/azents/e2e && uv run ruff check src`
  - `cd testenv/azents/e2e && uv run pyright .`
  - deterministic External Channel E2E for Slack HTTP, Slack Socket Mode, and Discord
    Gateway, including duplicate/concurrent and failure paths;
  - runtime-provider progress-control E2E without expected-failure markers;
  - generated OpenAPI/client drift checks when any API-relevant source is changed;
  - TypeScript format, lint, typecheck, and build only when TypeScript or generated
    artifacts are changed;
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - `python -m unittest scripts.tests.test_gen_docs_index`
  - `git diff --check`
- Scope-drift check:
  Compare the final diff with the deliverables and non-goals above. Remove living-spec
  edits, implementation dates, plan cleanup, unrelated refactors, new product behavior,
  compatibility fallbacks, legacy processor/hydration restoration, raw provider content,
  unbounded diagnostics, manual generated-client edits, live infrastructure/provider
  actions, and any claim that the external operational checkpoint has occurred.
- Context checkpoint:
  Record the complete matrix disposition, exact commands and aggregate results,
  environment and fixture prerequisites, Redis/memory lock evidence, failures and fixes,
  sanitization audit, current-spec deltas deferred to PR 9, independent review result,
  operational merge/deployment blocker, and remaining PR 9/10 scope before opening PR 8.
