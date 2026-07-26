---
title: "Unified Agent Input Mailbox Validation Report"
created: 2026-07-26
document_role: supporting
document_type: supporting-validation-report
snapshot_id: mailbox-260726
tags: [agent, mailbox, validation, e2e, migration, testenv]
---

# Mailbox Phase 6 Validation Report

## Scope and provenance

- Validation date: July 26, 2026 (KST).
- Branch: `feature/mailbox-260726-validation`.
- Validation range: `cdf40c80..e2211c4d`, including the Phase 5 web lifecycle implementation and Phase 6 validation changes.
- Current validation revision: `e2211c4d`.
- Phase boundary: no living-spec, Requirements, ADR, API redesign, or generated-client source changes were made in Phase 6.

## Environment and prerequisites

| Component | Observed value |
| --- | --- |
| Python | 3.14.6 |
| Node.js | v24.18.0 |
| pnpm | 11.15.1 |
| uv | 0.11.1 |
| Docker executable | unavailable (`docker: not found`) |
| Docker socket | unavailable (`/var/run/docker.sock` absent) |
| Chromium/browser automation | unavailable in the runtime |

The missing Docker substrate blocks Testcontainers PostgreSQL, the full testenv fixture stack, browser Web Surface/Selenium lanes, and containerized provider lanes. These lanes are **blocked**, not passed or product-level skips.

## Executed validation

### Web TypeScript and frontend tests

| Command | Result |
| --- | --- |
| `cd typescript && pnpm run format` | passed; files unchanged |
| `cd typescript && pnpm run lint` | passed; 5 workspace packages |
| `cd typescript && pnpm run typecheck` | passed; 5 workspace packages |
| `cd typescript && pnpm exec turbo run typecheck --filter=@azents/web` | passed |
| `cd typescript && pnpm --filter @azents/web test` | passed; 125 tests |
| `cd typescript && pnpm --filter @azents/web build-storybook` | passed; pending mailbox stories included in static build |
| `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check` | passed |
| `git diff --check` | passed |

A real Storybook/browser screenshot review was not run because no browser executable or automation package is available. The static Storybook build confirms compilation and story inclusion only; it is not visual-pass evidence.

### Backend and migration-focused tests

| Command | Result |
| --- | --- |
| `cd python/apps/azents && uv run pytest -q src/azents/rdb/mailbox_migration_preflight_test.py src/azents/services/chat/live_events_test.py src/azents/transport/chat_test.py` | passed; 18 passed, 1 skipped |
| `cd python/apps/azents && uv run ruff format --check ...mailbox_migration_integration_test.py && uv run ruff check ... && uv run pyright ...` | passed |
| `cd python/apps/azents && uv run pytest -q src/azents/rdb/mailbox_migration_integration_test.py` | blocked by missing Docker; 2 tests skipped by prerequisite fixture |
| `cd python/apps/azents && uv run ruff format --check src/azents/rdb/mailbox_migration_integration_test.py && uv run ruff check src/azents/rdb/mailbox_migration_integration_test.py && uv run pyright src/azents/rdb/mailbox_migration_integration_test.py` | passed after seed-order fix |
| `cd python/apps/azents && uv run pytest -q src/azents/rdb/mailbox_migration_integration_test.py --collect-only -q` | passed; 2 tests collected |

The migration integration fixture covers upgrade from `cc31dfa97a1b` to `8bbe580fddad`, all typed mailbox kinds, compound External Channel item order, downgrade restoration, and invalid External Channel preflight rejection. Its database execution remains blocked in this environment.

### Testenv and E2E validation

| Command | Result |
| --- | --- |
| `cd testenv/azents/e2e && uv run pytest -q src/tests/test_slack_provider_fake.py src/tests/test_external_channel_progress_proxy.py src/tests/test_support_utils.py src/tests/test_runtime_provider_auth.py src/tests/test_github_validation_proxy.py` | passed; 26 passed |
| `cd testenv/azents/e2e && uv run pytest ...test_chat_input_buffer.py ...test_agent_execution_persistence.py --collect-only -q` | passed; 14 tests collected |
| Changed-file Ruff/format/Pyright checks for the two public E2E modules | passed |
| Native mailbox E2E `test_ws_mailbox_upsert_and_remove_use_native_identity` | blocked during fixture setup by `docker.errors.DockerException` because `/var/run/docker.sock` is absent |

The collected public E2E coverage asserts native envelope/item identity, typed mailbox REST projection, WebSocket upsert/removal actions, promotion into durable history, FIFO follow-up promotion, deletion behavior, and no legacy `input_buffers` field in the split REST contract. Runtime execution of Docker-backed scenarios requires the CI testenv lane.

## Scenario evidence matrix

| Scenario | Evidence | Status |
| --- | --- | --- |
| Native mailbox envelope/item identity | Public E2E assertion and web reducer tests | passed at test/collection/static level; Docker execution blocked |
| FIFO envelope and item order | Reducer test and changed public E2E helper/assertions | passed |
| Durable promotion suppression and no delayed resurrection | Reducer test plus backend/public contract coverage | passed at unit/static level; Docker execution blocked |
| Action handoff ownership suppression | Web reducer/refresh implementation and action projection wiring | implementation covered; dedicated Docker E2E blocked |
| External Channel compound envelope ordering | Storybook compound fixture and migration fixture assertions | static/story/fixture coverage passed; Docker execution blocked |
| Refresh/reconnect baseline reconciliation | Resync generation/epoch guards and baseline reducer implementation | implementation/static checks passed; browser and Docker E2E blocked |
| Detached history isolation | Container ignores live/mailbox actions while detached and only marks newer history | implementation/static checks passed; browser E2E blocked |
| Delete dim, rollback, success suppression/resync | Delete reducer states and container mutation callbacks | implementation/static checks passed; Docker/browser E2E blocked |
| Read-only/authorization denial | Existing public authorization path remains unchanged; no new backend/API behavior | dedicated runtime lane blocked; no product behavior change claimed |
| Wait outcomes and signal-loss reconciliation | Existing backend suites remain green; broader Docker E2E is unavailable | focused backend passed; full E2E blocked |
| PostgreSQL migration upgrade/downgrade | Integration fixture implemented and collected | execution blocked by Docker |

## Generated contract and scope review

- OpenAPI input files were not changed by this phase.
- `cd python/apps/azents && uv run python src/cli/dump_openapi.py` — passed; regenerated public and admin OpenAPI snapshots.
- `cd python/libs/azents-public-client && make generate` — passed; regenerated the Python public client.
- `cd typescript && pnpm run generate --filter=@azents/public-client` — passed; regenerated the TypeScript public client.
- Generated output produced no tracked diff. No generated-client drift was identified.
- Phase 6 changed only deterministic validation fixtures/tests, the migration integration test, the Phase 6 plan, and this validation report.
- The living spec was intentionally not edited. The single `/spec-review` result below records all deferred candidates and Phase 7 owns the typed mailbox spec update and implementation-date snapshot promotion.

## Failures, fixes, and blocked lanes

- Migrated public E2E helpers from legacy `input_buffers` projections to native `mailbox_items` envelopes and `(mailbox_item_id, item_key)` identity.
- Migrated the pending-delete E2E helper to `DELETE /chat/v1/sessions/{session_id}/mailbox-items/{mailbox_item_id}`, passing the accepted native `mailbox_item_id` and asserting the removed envelope cannot reappear or reach model history.
- Added public WebSocket coverage for `mailbox_item_upserted` and `mailbox_item_removed` with durable history convergence assertions.
- Added Docker-backed migration integration coverage for all typed kinds, compound External Channel ordering, downgrade, and malformed-row rejection.
- The independent review initially found a stale legacy delete helper, an imprecise generation claim, and a spec-review record mismatch; all three findings were fixed in the working tree.
- A subsequent review found a migration fixture FK seed-order defect. `_seed_valid_database()` now inserts identity, all pre-mailbox `input_buffers` rows, and only then the External Channel graph; this was rechecked with Ruff/Pyright and test collection.
- Affected E2E format/lint/Pyright checks passed after the delete-helper fix; the two public E2E modules still collect 14 tests.
- No product behavior failure was observed in the available non-Docker tests.
- Docker-backed migration, full testenv, browser Web Surface/Selenium, and provider-container lanes are blocked by the exact prerequisite failures recorded above.
- Visual review is blocked by the absence of browser automation; Storybook static compilation passed but is not a rendered screenshot verdict.

## `/spec-review` result

Executed on July 26, 2026 (KST) against the complete Phase 5 implementation range `cdf40c80..e2211c4d` plus the current working-tree validation/report changes. Changed frontend paths were matched against every `docs/azents/spec/**/*.md` `code_paths` entry.

### Impacted specs deferred to Phase 7

- `docs/azents/spec/flow/chat-session-resync.md`
  - The current body still names `input_buffers` as the `/live` pending field and does not describe `mailbox_item_upserted` / `mailbox_item_removed`, typed envelope/item identity, durable/action precedence, or native pending reconciliation.
  - Phase 7 should update the REST/WS contract, baseline generation/epoch rules, detached-history behavior, and pending rendering terminology, then refresh `last_verified_at`.
- `docs/azents/spec/domain/conversation.md`
  - Current behavior sections still describe FIFO `input_buffer` transport and `action_executions` keyed by `input_buffer_id`; the mailbox implementation now exposes typed mailbox envelopes/items and `source_mailbox_item_id` action ownership.
  - Phase 7 should update the current domain terminology and correlation model, then refresh `last_verified_at`.
- `docs/azents/spec/domain/goal.md`
  - Goal continuation transport and UI sections still describe continuation `InputBuffer` rows and legacy pending presentation. Phase 7 should reconcile the typed `goal_continuation` mailbox projection with the existing Goal-specific display and mutation-control rules.

### Matched specs with no Phase 6 update required

- `docs/azents/spec/flow/agent-execution-loop.md` — matched chat renderer/container paths, but this Phase 5/6 work changes only pending projection presentation and validation coverage; execution-loop behavior remains documented for later spec promotion.
- `docs/azents/spec/flow/file-exchange-storage.md` — `ChatView` match is via shared attachment rendering; mailbox pending projection does not change file-exchange ownership or storage behavior.
- `docs/azents/spec/flow/session-context-inspector.md` — matched session view/container paths, but context-inspector behavior is unchanged.
- `docs/azents/spec/flow/kimi-oauth.md` — broad chat path match only; provider OAuth behavior is unchanged.
- `docs/azents/spec/flow/test-strategy-e2e-primary.md` — validation tests are evidence for this phase and do not require changing the living test-strategy contract.

No living spec was edited in Phase 6. The later Spec Promotion phase owns these deferred updates and implementation-date snapshots.

## Review status

The final same-reviewer read-only recheck by `/root/mailbox-reviewer` returned **CLEAN** on July 26, 2026 (KST).

The review findings were resolved as follows:

- Legacy pending-delete E2E helper migrated to the native `/mailbox-items/{mailbox_item_id}` endpoint and real mailbox identity, with removal/non-resurrection assertions.
- Generated-client evidence corrected by explicitly running the public OpenAPI dump, Python public-client generation, and TypeScript public-client generation commands; all passed with no tracked generated diff.
- The Phase 6 plan's recorded `/spec-review` result aligned with this report: `chat-session-resync.md`, `conversation.md`, and `goal.md` are deferred to Phase 7 without editing living specs in Phase 6.
- Migration fixture FK seed order corrected so pre-migration `input_buffers` rows are inserted before the External Channel batch references `mailbox-external-migration`.

The Docker-backed PostgreSQL migration tests remain **blocked**, not passed: the final runtime check collected two tests but skipped execution because `/var/run/docker.sock` is absent. No new review cycle is required for this report-only accuracy update.
