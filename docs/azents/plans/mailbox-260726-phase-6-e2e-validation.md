---
title: "Unified Agent Input Mailbox Phase 6: E2E and Validation"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, mailbox, e2e, testenv, migration, validation, plan]
---

# Mailbox Phase 6: E2E and Validation

## Phase Execution Plan

- Phase: `6 — E2E and validation`
- Branch/base: `feature/mailbox-260726-validation` → `feature/mailbox-260726-web-lifecycle`
- PR boundary: Add deterministic mailbox validation fixtures and E2E/API/WS/migration coverage, execute every available validation lane, fix product or fixture defects found, run `/spec-review` once, and publish a supporting validation report. Do not update living specs or mark the snapshot implemented in this phase.
- Inputs: [`mailbox-260726/REQ`](../requirements/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/ADR`](../adr/mailbox-260726-unified-agent-input-mailbox.md), [`mailbox-260726/DESIGN`](../design/mailbox-260726-unified-agent-input-mailbox.md), the [multi-phase implementation plan](mailbox-260726-implementation-plan.md), and completed [Phase 1](mailbox-260726-phase-1-persistence.md) through [Phase 5](mailbox-260726-phase-5-web-pending-lifecycle.md) plans.
- Deliverables:
  - Native mailbox API/WS/browser E2E coverage for typed pending state, promotion, refresh/reconnect, detached mode, delete/read-only, all source kinds, and operation action handoff.
  - Deterministic compound External Channel context-plus-trigger fixture coverage without live provider credentials.
  - Real PostgreSQL migration upgrade coverage from the pre-mailbox revision with every kind, valid External Channel batch, malformed/unresolvable preflight, and rollback boundary evidence.
  - Executed validation commands and a supporting report under `docs/azents/design/` recording environment, fixture readiness, matrix evidence, failures/fixes, blocked lanes, and implementation-versus-spec drift.
  - One `/spec-review` result recorded for the later Spec Promotion phase.
- Non-goals:
  - No speculative product behavior, API/client/schema redesign, Requirements/ADR/Design edits, or living-spec edits.
  - Do not report a blocked Docker/browser/migration substrate as a passing product scenario.
  - Do not use direct product DB writes for runtime E2E setup; migration tests may seed pre-migration SQL deliberately.
- Interfaces:
  - E2E assertions use public REST/WS/browser behavior and semantic DOM/API evidence; testenv fixture setup owns infrastructure prerequisites.
  - Typed pending identity is `(mailbox_item_id, item_key)`; validation checks all source kinds, compound envelope ordering, durable/action precedence, and no legacy public pending contract.
  - Migration fixture upgrades `cc31dfa97a1b` to `8bbe580fddad`; application behavior does not use pre-migration rows outside that isolated migration test.
  - Validation report distinguishes `passed`, `blocked`, and `not-run`; only executed passing evidence may be called passed.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| E2E/testenv, migration validation, fixes, and report | `/root/mailbox-implementer` | `testenv/azents/e2e/**`; mailbox migration integration tests; focused product tests only when a validation finding requires a fix; `docs/azents/design/mailbox-260726-validation-report-2026-07-26.md`; Phase 6 plan | Phases 1–5 | Deterministic fixtures/tests, executed evidence, product/fixture fixes, validation report | Testenv format/lint/typecheck/pytest lanes; backend migration/product suites; workspace checks; `/spec-review`; docs checks |
| Independent review | `/root/mailbox-reviewer` | Read-only Phase 6 diff, report, commands, and evidence | Implementer validation | Grounded findings and recheck verdict | Matrix completeness, fixture realism, migration lane, blocked-vs-passed honesty, fix scope, spec-impact record |

- Integration order:
  1. Run `/spec-review` once against the implemented stack and record matched current-spec drift candidates; defer actual spec edits to Phase 7.
  2. Migrate/extend legacy chat-input and WS E2E harnesses to the typed `mailbox_items` and `mailbox_item_upserted`/`mailbox_item_removed` contract.
  3. Add provider-independent fixtures for all-kind pending state, compound External Channel envelope, Turn Action handoff, Goal/Agent input, wait/terminal queue-only behavior, and authorization/read-only mutation.
  4. Add the Docker-backed Alembic upgrade fixture following existing migration integration patterns.
  5. Execute the deterministic API/WS lane, Web Surface lane, migration lane, focused backend contract lane, and full backend/TypeScript quality lanes where prerequisites exist. Fix behavior or fixture defects found.
  6. Write the supporting validation report with exact KST dates, commits, commands, fixture provenance, scenario evidence, failures/fixes, blocked environments, and spec drift.
  7. Compare final diff against non-goals and request independent review; apply findings and revalidate.
- Independent review: `/root/mailbox-reviewer` verifies that public E2E uses real behavior rather than product DB shortcuts; every matrix scenario is passed or honestly blocked with evidence; migration validates a real revision upgrade; the report separates fixture, environment, and product failures; and spec edits remain deferred.
- Final validation:
  - `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run pyright . && uv run pytest -vv`.
  - Focused mailbox projection/promotion/terminal/migration tests.
  - `cd testenv/azents/e2e && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src`.
  - `cd testenv/azents/e2e && uv run pytest -vv -m "web_surface and not live_external and not runtime_provider" ./src`.
  - Full TypeScript format, lint, typecheck, build; docs index; `git diff --check`; and reviewer `CLEAN`.
- Scope-drift check: permit deterministic validation fixtures/tests, migration integration evidence, fixes directly found by the matrix, and the validation report. Move specs, API redesign, feature expansion, and cleanup to their assigned phases.

## Validation Matrix

| Scenario | Required public evidence |
| --- | --- |
| User mailbox item during active descendant wait | `wait` activity, typed pending REST/WS item, one durable promotion, history before removal. |
| Agent message and Goal continuation | Source-specific pending presentation and normal promotion through the mailbox. |
| Queue-only send and terminal result | Active wait observes delivery; idle parent remains unstarted; terminal state and direct-parent mailbox result are atomic. |
| Turn Action handoff | Pending item, `action_execution_updated`, pending removal, and durable result preserve source mailbox correlation and order. |
| External Channel compound envelope | Context-plus-trigger items are contiguous and immutable after source mutation/removal; refresh/reconnect reconstructs safe pending presentation. |
| Native Web reconciliation | Duplicate/reordered mailbox WS frames and accepted REST baseline converge by envelope/item identity; stale pending loses to durable/action ownership. |
| Detached history and deletion | Live mailbox actions do not mutate detached visible state; allowed deletion dims then rolls back/resyncs on failure; subagent/read-only denial remains intact. |
| Wait outcomes | No descendant, all idle, default/explicit timeout, and signal-loss reconciliation preserve structured result contract. |
| Migration | Pre-mailbox fixture upgrade preserves IDs/FIFO/idempotency/FKs and typed payloads; malformed External Channel row aborts before destructive removal; rollback boundary is recorded. |

## Environment and Reporting Rules

The local runtime as of July 26, 2026 has no `docker` executable or `/var/run/docker.sock`. Docker-backed Postgres migration, full testenv, browser Web Surface, Selenium, and containerized provider lanes are therefore blocked locally unless the environment changes. Record the exact failed prerequisite and expected CI lane; do not label those scenarios skipped/pass.

The validation report must use KST dates and include: branch/commit range; environment versions; prerequisite/fixture status; commands and exit results; scenario-to-API/WS/DOM evidence; migration upgrade/downgrade outcome; generated-contract evidence; failures/fixes/reviews; blocked lanes; and implementation-versus-living-spec drift. It must state that the later Spec Promotion phase owns spec edits and snapshot implementation dates.
