---
title: "Team Session execution boundaries phase 8: deterministic validation report"
created: 2026-07-24
tags: [session, authorization, validation, e2e, testenv, migration, security]
---

# Team Session execution boundaries phase 8: deterministic validation report

## Scope and Boundaries

- Phase: `8/10 — Deterministic E2E and validation`
- Branch/base: `validate/team-session-execution-boundaries` → Phase 5 (`083f49d7`)
- Requirements: [session-260724/REQ](../requirements/session-260724-team-session-execution-boundaries.md)
- ADR: [session-260724/ADR](../adr/session-260724-team-session-execution-boundaries.md)
- Design: [session-260724/DESIGN](../design/session-260724-team-session-execution-boundaries.md)
- Delivery plan: [Team Session execution boundaries implementation plan](./team-session-execution-boundaries-implementation-plan.md)
- Earlier phase plans: [Phase 1](./team-session-execution-boundaries-phase-1-admission-provenance.md), [Phase 2](./team-session-execution-boundaries-phase-2-canonical-execution.md), [Phase 3](./team-session-execution-boundaries-phase-3-userless-engine.md), [Phase 4](./team-session-execution-boundaries-phase-4-resource-authority.md), and [Phase 5](./team-session-execution-boundaries-phase-5-cutover-replay.md)

This phase adds only deterministic testenv/E2E validation evidence, fixture support, and fixes that
are directly demonstrated by validation. It does not promote living specifications, set `implemented`
dates, remove plans, create a compatibility path, perform a live cutover, or write to a shared or
production database.

## Environment and Readiness Contract

Required validation uses local Docker-backed PostgreSQL, Valkey, RustFS, AIMock, Slack fake, and the
locally enrolled Docker Runtime Provider. It uses public/admin APIs for product setup. Scenario tests
must not mutate product rows directly. Pre-migration SQL is permitted only in migration integration
tests.

Before product E2E runs, execute:

```console
cd testenv/azents
uv run testenv fixture doctor --all --json
```

A missing deterministic fixture is a recorded blocked result, not a skip or success. The required E2E
lane is:

```console
cd testenv/azents/e2e
uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src
```

Runtime Provider coverage is a separate deterministic lane, and must report readiness before running:

```console
uv run pytest -vv -m "runtime_provider and not live_external" ./src/tests/azents/public
```

Optional live lanes retain their existing `live_external` policy and are not run for this validation.

## Executed Evidence

| Time (KST) | Command | Result | Evidence |
| --- | --- | --- | --- |
| 2026-07-24 | `cd testenv/azents && uv run --with ruff ruff check ... && uv run --with ruff ruff format --check ... && uv run --with pyright pyright ... && uv run pytest testenv/tests/test_devserver_fixture.py` | pass | Ruff and format checks passed, Pyright reported `0 errors, 0 warnings`, and Pytest reported `10 passed in 0.09s`. |
| 2026-07-24 | `cd testenv/azents/e2e && uv run --with ruff ruff check ... && uv run --with ruff ruff format --check ... && uv run --with pyright pyright ... && uv run pytest --collect-only -q ...` | pass | The two-member Team Session and file-resource E2E changes passed Ruff, format, and Pyright; all 16 focused tests collected. |
| 2026-07-24 | `cd testenv/azents && uv run testenv fixture doctor --all --json` | blocked | Exit code `1`; structured JSON reported missing devserver state/manifest, absent tmux session, unhealthy public/admin endpoints, and a missing `agent-basic` manifest/private state. No traceback occurred. |
| 2026-07-24 | deterministic and Runtime Provider E2E lanes | blocked | The required readiness gate failed, so neither product E2E lane was started or reported as a skip/success. |
| 2026-07-24 | `cd python/apps/azents && uv run alembic -c db-schemas/rdb/alembic.ini heads` | pass | Reported the single expected head `374a722fb9ee`; `db-schemas/rdb/revision` contains the same revision. |
| 2026-07-24 | `pre-commit run --all-files` | pass | All hooks passed, including docs validation/index generation, Ruff, OpenAPI dump verification, Python/Testenv Pyright, and TypeScript format/lint/typecheck. |

The focused source checks and test collection do not substitute for product E2E execution. The local
deterministic product lanes remain blocked by fixture readiness.

## Fixture Audit and Required Additions

Existing deterministic coverage provides AIMock, RustFS, Slack fake, Docker Runtime Provider,
execution-persistence, subagent, provider-image, client-image, and file-resource lifecycle suites.
The testenv broker devtool accepts only `session_id` and emits `SessionWakeUp(session_id=...)`, which
matches the pure-routing contract.

This phase adds a reusable two-member Team Session helper that creates both users, Workspace
membership, Agent, and root Team Session exclusively through public/admin APIs. It exposes both
member tokens and the removable member's WorkspaceUser identity without direct product-row mutation.
Its focused test is collected but cannot execute until the deterministic devserver is ready.

The following support remains absent:

1. A bounded Worker restart helper that restarts only the local
   `azents_engine_worker_container` and waits with a fixed timeout for its `/readyz` endpoint.
2. A one-shot post-commit broker-notification failure control in the Public API process. The existing
   testenv broker injection endpoint can send a later pure wake-up, but it cannot fail the Public
   API's next matching wake-up after the admission transaction commits.
3. A migration integration fixture with representative pre-migration rows, used only by migration
   integration tests, which reports sender/source/ModelFile lineage classification counts.

## Required Matrix and Evidence Status

| Scenario | Existing candidate coverage | Required evidence | Status |
| --- | --- | --- | --- |
| Two members send to one Team Session | reusable public/admin API helper and focused E2E added in `test_team_sessions.py` | distinct durable `sender_user_id` values and unchanged Team capability behavior | test collected; execution blocked by devserver readiness |
| Unauthorized or removed member writes and reads | Agent-scoped upload access tests enabled; legacy session-list tests remain blocked | denied status plus no input/resource/history disclosure | blocked by missing current API-focused journey and devserver readiness |
| Sender removed after attachment admission | file upload plus lifecycle suites | admitted file promotes; current member reads; removed member denied | blocked by missing focused journey and devserver readiness |
| Worker restart before promotion | execution persistence/runtime suites; single Worker container and readiness endpoint identified | one promotion, retained FilePart, no sender execution context | blocked by missing bounded restart helper and devserver readiness |
| Different member continues file-bearing history | file upload AIMock journal; two-member helper available | existing FilePart remains model-visible | blocked by missing focused journey and devserver readiness |
| External Channel invocation | `test_external_channels.py` with Slack fake | provider principal work executes with no Azents User | blocked by devserver readiness |
| Subagent delivery and recovery | `test_subagents.py` | SessionAgent/Run lineage without User | blocked by devserver readiness |
| Agent Memory available; User Memory absent | no focused Team E2E identified | Agent Memory tool available and User Memory absent | blocked by missing focused AIMock Tool journey |
| Present/import/read/MCP output survives recovery | `test_file_resource_lifecycle.py` | Session/Run authority survives recovery | blocked by Runtime Provider and devserver readiness |
| Provider/client generated image succeeds once | `test_provider_image_generation.py`, `test_xai_image_generation.py` | one deterministic output identity without User | blocked by devserver readiness |
| Public resource access matrix | Agent-scoped upload tests enabled; legacy `TestExchangeFiles` remains skipped because its session-list API is unavailable | member allowed; non-member and stored source denied | blocked by missing current API-focused resource journey and devserver readiness |
| Broker notification failure | admission/idempotency unit coverage exists | accepted input executes exactly once through retry/recovery | blocked by missing one-shot notification fault control |
| Cutover fixture | Phase 5 migration/replay tests | classification counts and pure-wake replay smoke | blocked by missing local migration integration fixture |

## Grounded Fixes Found During Validation

| Finding | Evidence | Fix | Verification |
| --- | --- | --- | --- |
| `fixture doctor --all` crashed when `tmux` was absent instead of reporting fixture readiness. | Initial doctor invocation raised `FileNotFoundError` from `subprocess.run(["tmux", ...])`. | `tmux.has_session()` returns `False` when `tmux` is absent. | `test_devserver_fixture.py`: 10 passed; doctor now returns structured JSON with exit code 1. |
| Two-member Team Session sender provenance had no public/admin API E2E journey. | Existing Team Session tests covered only one authenticated member. | Added a reusable two-member helper and a focused same-Session write test that polls durable history before asserting each admitted `sender_user_id`. | Ruff, format, and Pyright passed; the focused test collected and awaits deterministic fixture readiness. |
| Agent upload tests retained a stale Phase 1 bootstrap skip after Team primary Session bootstrap became available. | `TestFileUpload` can use the current Agent-scoped upload API and Team primary Session setup; `TestExchangeFiles` still targets an unavailable session-list API. | Removed the `TestFileUpload` class skip and aligned its helper/access tests with the Agent-scoped API. Retained `TestExchangeFiles` as blocked with an accurate reason instead of treating it as validated. | All 16 focused Team/file tests collected; enabled execution awaits deterministic fixture readiness. |

## Generated Client and Migration Evidence

- Generated public clients: no public schema changed and no generated client file is modified. The
  fixture uses the existing generated invitation and WorkspaceUser methods with their current
  signatures.
- Alembic revision/head and migration classification: blocked by the missing local Docker migration
  integration fixture.
  No shared database migration, stamp, upgrade, downgrade, or production data operation is permitted.
- Classification counts: unavailable until the migration integration fixture can execute. Record
  explicit `null` Human sender, `migration` Exchange provenance, and nullable unmatched ModelFile Run
  counts when the fixture is runnable.

## Implemented Behavior Versus Current Living Specs

This phase intentionally does not modify living specs. The strict comparison below identifies the
expected Phase 9 promotion work and validation evidence needed to support it.

| Current living spec | Implemented behavior under comparison | Current spec coverage | Phase 8 action |
| --- | --- | --- | --- |
| `spec/domain/conversation.md` | Team admission, sender-bearing inputs, requester/public read separation, canonical Session work | Does not yet describe this complete `session-260724` boundary set | collect evidence only; promote in Phase 9 |
| `spec/flow/agent-execution-loop.md` | pure wake-ups, canonical snapshots, Userless execution, recovery, resource authority | Does not yet describe the complete Phase 1–5 cutover contract | collect evidence only; promote in Phase 9 |
| `spec/flow/run-resume.md` | Userless recovery and durable replay | requires Phase 8 replay/recovery evidence | collect evidence only; promote in Phase 9 |
| `spec/flow/file-exchange-storage.md` | Session/Run resource authority, provenance, ModelFile lineage, public read separation | requires Phase 8 file/resource evidence | collect evidence only; promote in Phase 9 |
| `spec/domain/toolkit.md` | stable Team toolkit lifecycle and no User fallback | requires multi-sender/recovery evidence | collect evidence only; promote in Phase 9 |
| `spec/domain/memory.md` | Agent-only Team Memory projection | requires focused Team Memory evidence | collect evidence only; promote in Phase 9 |
| `spec/domain/external-channel.md` and `spec/flow/external-channel-authorization.md` | provider-principal execution with no Azents User | requires Slack-fake E2E evidence | collect evidence only; promote in Phase 9 |
| `spec/flow/periodic-execution.md` | cleanup/recovery scans for new provenance and lineage | requires migration/resource evidence | collect evidence only; promote in Phase 9 |

## Completion Commands

Run focused checks before the complete matrix. Record exact output and failure causes in this report.

```console
cd testenv/azents
uv run pytest testenv/tests/test_devserver_fixture.py
uv run testenv fixture doctor --all --json

cd ../e2e
uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src
uv run pytest -vv -m "runtime_provider and not live_external" ./src/tests/azents/public

cd ../../../python/apps/azents
uv run ruff check --fix .
uv run ruff format .
uv run pyright
uv run pytest

git diff --check
```

Each required matrix row above is either backed by executed focused evidence or records its exact
deterministic blocker. This report does not claim complete product E2E verification while those
blockers remain. No optional/live result substitutes for a required local result.
