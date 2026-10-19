---
title: "Session Routines Verification Evidence"
created: 2026-10-19
tags: [routine, verification, testenv, frontend, scheduler]
document_role: supporting
document_type: supporting-verification
snapshot_id: routine-261018
---

# Session Routines Verification Evidence

This supporting record preserves validation evidence for
[routine-261018/REQ](../requirements/routine-261018-session-routines.md),
[ADR-D2/D3/D4](../adr/routine-261018-session-routines.md) and
[Design revision 2](routine-261018-session-routines.md). Current behavior belongs
in the [Routine Spec](../spec/domain/routine.md) and linked cross-domain Specs.
Design delta: None. M1/M2/M4-M12 are implemented; M3 remains retired. Validation
introduces no new judgment owner, lease/retry lifecycle, versioning, destination
selector or public management/run API.

## Environment and Provenance

- Phase 5 branch: `feat/routine-261018-5-verification`, based on Phase 4
  `eeb9724662b12fd9b03bccf43cd7fa4939325375`. Phase 1-4 PRs:
  [#2328](https://github.com/azents/azents/pull/2328),
  [#2329](https://github.com/azents/azents/pull/2329),
  [#2335](https://github.com/azents/azents/pull/2335),
  [#2336](https://github.com/azents/azents/pull/2336).
- Primary implementation/integration/validation owner: `/root`. Single independent
  read-only reviewer: `/root/routine-reviewer`; final complete Phase 5 review found
  **0 actionable findings** across the stable 34-file diff.
- Local Linux Docker client/server 29.8.2; isolated content-matched E2E containers,
  PostgreSQL, existing Public/Admin API, real Worker, Scheduler service and Docker
  Runtime. No managed devenv or copied production Session data is used.
- Product mutations use actual Agent tools or public APIs. E2E performs no direct
  product database writes. Narrow repository/migration tests own database fixtures.
- `__testenv_model_listing:deterministic-routine` explicitly declares Structured
  support. Selection is saved through the ordinary Agent API; other deterministic
  variants retain absent capability evidence. Canonical OpenAI Responses requests
  replay their stored native continuation context.
- Source instants `2099-01-01T00:00:00Z` and `2099-01-01T00:30:00Z` are controlled
  test inputs, not Worker clock changes. The test first proves no-action, then
  selection; it never bypasses the real-clock minimum action delay.
- Standard `AZENTS_E2E_ARTIFACT_DIR` retains safe request-shape journals, actual
  work snapshots, Runtime output, management/restore evidence and Web screenshots.
  CI records `CI_HEAD_SHA`; local dirty-worktree evidence is explicitly labeled
  `local_worktree` rather than falsely assigning a commit to uncommitted changes.

## Commands and Established Results

From `python/apps/azents`:

- Full backend after the native Structured endpoint correction:
  `uv run pytest -q` — **13,235 passed, 3 skipped**, 345.73 seconds. The three
  existing skips are not skips of the required deterministic product journey.
- Related provider/context/normalizer/native tests — **208 passed**.
- Routine repository/service/engine/tool/worker/inspection/migration, Scheduler
  route and deterministic-listing final focused collection — **203 passed**, 40.55s.
- Held Structured-call input-preservation service matrix — **12 passed** after
  the additional concurrency case; Ruff/format and full backend `ty` pass.
- Explicit capability-listing fixture validation — **23 passed**.

From `testenv/azents/e2e`:

```sh
AZENTS_E2E_IMAGE_BUILD_PROFILE=required \
AZENTS_E2E_ARTIFACT_DIR=<artifact-root> \
uv run pytest -q src/tests/required/public/test_routines.py --junitxml=<junit>

AZENTS_E2E_IMAGE_BUILD_PROFILE=web \
AZENTS_E2E_ARTIFACT_DIR=<artifact-root> \
uv run pytest -q src/tests/web/public/test_routines.py --junitxml=<junit>
```

- Initial full work journey: **1 passed**, 48.57s (`required-attempt5`).
- Expanded management/authority/archive/restore journey: **1 passed**, 55.56s
  (`management3`). Execution, management and restore JSON were captured before
  teardown and recursively checked for auth/token/key/cookie fields and the
  synthetic API key: none found.
- Real deployed Web journey: **1 passed**, 79.65s (`web2`). Actual login, exact
  Session panel, product-created objective, keyboard-expanded judgment and
  refresh/reload collapse were observed. `routine-web-panel.png` and
  `routine-web-judgment.png` are actual browser captures, not fixture-only renders.
- Full Docker-free E2E support collection: **1,472 passed**, 13.60s, including
  14 Routine fixture/barrier cases and isolated stdlib-only proxy import with all
  packaged fixture modules. E2E Ruff/format and `ty --error-on-warning` pass.
- Actual Runtime-held FIFO/Stop product boundary: **passed**, 13.674s testcase
  wall in the first boundary collection. A real Runtime HTTP barrier holds an
  ordinary tool while Scheduler queues judgment; explicit release permits one
  no-action check. Later selected Routine work is held at the same real boundary;
  public Stop cancels both incomplete occurrences, preserves definitions and
  records no result. `fifo-stop.json` retains the actual provider requests and
  cancelled snapshots.
- Final integrated required collection: **4 passed**, 115.94s, including the
  management/default-chat journey, actual Primary Slack delivery success,
  Primary publication failure without Session-chat fallback/retry, and held
  Runtime FIFO/Stop. Both Primary cases observed exactly one `chat.postMessage`
  attempt while objective outcome and work recording remained independent.
- Final integrated Web rerun: **1 passed**, 77.80s, against the same final helper
  and proxy implementation. Actual panel and judgment captures are retained.

Local evidence filenames use `routine-phase5-<attempt>.log`, matching JUnit XML
and `<attempt>-artifacts/`. Earlier attempts are retained separately and are not
overwritten by successful reruns. Required deterministic flows do not skip for
missing external credentials.

## E1-E20 Traceability and Layer Ownership

Paths below are relative to `python/apps/azents/src/azents/` unless stated.
`product` means the required journey in `test_routines.py`; `web` means the
Web-owned journey. Exhaustive permutations remain at their narrowest valid layer.

| ID | Product-boundary evidence | Narrow evidence and obligations |
| --- | --- | --- |
| E1 | product: actual create/list/inspect/update/delete; other-Session and non-member 404 | `repos/routine/persistence_test.py`: exact update, mismatch, wrong scope, twenty-first definition rejection |
| E2 | product: Scheduler dispatch without clicks; creation does not check immediately | `services/routine/source_dispatch_test.py`, `scheduler/routine_source_dispatch_test.py`, `core/routine_test.py`: supported sources and empty eligibility |
| E3 | product: first no-action, later source tick selects; no fabricated Worker time | `repos/routine/judgment_inbox_test.py::test_delay_preserves_source_without_creating_an_exact_threshold_job`; source contention and independent references |
| E4 | product: joint two-candidate selection and incomplete continuation | `repos/routine/fifo_test.py`, `judgment_inbox_test.py::test_action_promotion_capture_and_atomic_settlement`, `services/routine/judgment_test.py` empty case |
| E5 | actual Runtime-held ordinary tool; source enqueues without a model overlap; explicit release then one no-action | `worker/run/routine_judgment_integration_test.py`: same-host later poll; `worker/run/turn_action_executor_test.py`: neutral dispatch and recovery; canonical no-tool wire in engine tests |
| E6 | barrier-held actual Structured SDK call, one native request, new user event and next tick preserved | `services/routine/judgment_test.py` input-during-call case; `repos/routine/judgment_inbox_test.py` settlement matrix |
| E7 | product: valid no-action then joint action, failed evidence fails fast | `core/routine_judgment_test.py`, `engine/routine_judgment*_test.py`: IDs, invalid/incomplete native terminal proof, usage and cleanup; service failure/next-tick matrix |
| E8 | product: original objective in trigger; real Runtime Shell output | `engine/events/routine_input_test.py`, `engine/tools/routine_test.py`: immutable admitted context and exact owner |
| E9 | product: one initial result then oldest-incomplete continuation | `engine/tools/routine_continuation_test.py`, `repos/routine/fifo_test.py`, `state_test.py`: other-context reads and admitted identity |
| E10 | product: silent finished Alpha; failed-objective notifying Beta | `core/routine_test.py`, `repos/routine/completion_test.py`, `services/routine/notification_test.py`: cross-field validation and independent recording/delivery |
| E11 | product: stale update rejected, exact update applied, other fields/records preserved | `repos/routine/persistence_test.py`, `judgment_inbox_test.py`: edits after capture retain admitted objective |
| E12 | product: exactly one record per definition and delete isolation | `repos/routine/persistence_test.py`: 101-to-100 trimming; `completion_test.py`: canonical duplicate and late deletion without resurrection |
| E13 | actual Runtime-held admitted work; public Stop cancels incomplete occurrences while preserving definitions | `repos/routine/stop_test.py`, `judgment_inbox_test.py` Stop/owner recovery; `lifecycle_test.py` archived recovery; `retry_test.py`; turn-action recovery tests |
| E14 | product: local originating-Session chat, no Team Primary misrouting; local Slack Primary success/failure with exactly one provider attempt and no chat fallback | `services/routine/notification_test.py`: post-commit publication, failed/unknown/raised/cancelled outcomes, current/replaced/invalid Primary, no fallback/retry; existing Slack/Discord delivery suites retain transport ownership |
| E15 | no production migration executed | real migration tests `rdb/models/routine*_migration_test.py`; `repos/routine/persistence_test.py`: zero/one/multiple connected Bindings, preserved connections and ambiguous rollback |
| E16 | web: persisted/reloaded collapsed judgment and keyboard expansion; product history | `core/routine_presentation_test.py`, `repos/routine/history_test.py`, `visibility_test.py`, session-core projections and Phase 4 interaction tests |
| E17 | product: 99,999-token judgment versus ordinary turns; no-action leaves usage/prompt/breakdown/turn count unchanged | `engine/routine_judgment_context_test.py`, `repos/routine/judgment_observation_test.py`; provider usage and compaction/input regressions |
| E18 | ordinary Runtime work in product; judgment-only neutrality in real repository | `repos/routine/judgment_observation_test.py::test_append_read_judgment_does_not_change_activity_or_context`; worker no-foreground-preparation integration |
| E19 | product: archive removes definitions/records; restore does not recreate; judgment IDs retained | `repos/routine/lifecycle_test.py`: started/pre-start, mixed provenance, owner recovery, real purge waiting and namespace absence; archived-session purge regressions |
| E20 | web: real read-only panel, product-created objective, native keyboard and reload | Phase 4 Storybook 30 and native 80 assertions; `routineToolPresentation.test.mts`, session-core and semantic tool interaction cases cover failures, cancellation, duplicates, mobile and state matrices |

## Defects and Test-Precondition Corrections

1. The first product journey exposed a real native Responses Structured-lowering
   bug: environment-derived Base URL defaults leaked into semantic request
   controls. A synthetic regression failed before correction. Ordinary and
   Structured paths now share the existing client-only filter; credential
   rejection remains strict. Full backend and provider checks passed afterward.
2. A default deterministic model lacked saved Structured capability. The fixture
   now declares it explicitly in its own variant and selects it via the API;
   product capability guards were not weakened.
3. Native stored-response continuation was missing from the model fixture. The
   fixture now replays prior response context instead of changing production
   transport or returning fake work results.
4. A test treated future source time as Worker time. It now respects independent
   clocks and no-action-before-action rather than bypassing delay.
5. The management test attempted to archive Team Primary. It now uses an ordinary
   Session and preserves the existing 409 protection. Primary channel Binding is
   explicitly distinguished from Team Primary Session.
6. The first Web assertion incorrectly used display title `Alpha` as objective
   identity; actual persisted objective is `ROUTINE_E2E a: ...`. Real screenshot
   and API data established the correct fixture value; product UI was unchanged.
7. New channel attempts initially omitted the dedicated External Channel Gateway
   and then expected approval while retaining default open access. The fixture
   now starts the Gateway and sets the same restricted policy as existing signed
   participation tests. The initial channel Work must also finish through real
   `tool_search`/`channel_action(ignore)` before isolated Routine continuation;
   otherwise the fixture cannot answer the channel continuation and strict mode
   reports `no_fixture_match`. These are explicit fixture preconditions, not
   product permission, continuation or notification policy changes.
8. The full support collection caught a standalone-import smoke fixture that
   copied only the older Browser module. It now copies both actual stdlib helper
   modules; isolated `-I -S` import still proves no site-package/listener dependency.

## Scope, Removal, External Actions and CI

No independent judgment owner/worker/lease/retry state, synthetic no-action,
ordinary usage/prompt pollution, hand-edited generated client, fallback
notification, arbitrary destination or new manual management surface was added.
The testenv exact-aware Scheduler endpoint delegates to the real dispatcher and
returns only admission counts. Existing Scheduled Task, Goal and Channel Work
contracts remain owned by their existing suites.

No live provider authorization, real external-channel publication, production
migration, merge or deployment is authorized or performed. Slack tests use the
local fake only. Real Slack/Discord/Bedrock/OAuth prerequisite snapshots were not
prepared or consumed; those optional live checks are **not executed**, not
reported as successful synthetic checks.

Phase 2 requested CI restart was triggered exactly once at `bcf846900`; run
[39163261120 attempt 2](https://github.com/azents/azents/actions/runs/39163261120)
succeeded. Phase 3 run
[39163260578](https://github.com/azents/azents/actions/runs/39163260578) succeeded.
Phase 1 run [39163261314](https://github.com/azents/azents/actions/runs/39163261314)
and Phase 4 run [39165617208](https://github.com/azents/azents/actions/runs/39165617208)
passed functional lanes but failed the unchanged duration gate:
544.019623s versus 413.575784s (+31.54%) and 535.029733s versus 408.692802s
(+30.91%; threshold 490.4313624s), respectively. Both artifact sets remain
preserved. The stack is **not green**; no blind rerun, reduced coverage or gate
relaxation has been used.

## Finalization Checkpoint

Functional validation and one full-stack Spec impact review are complete.
Requirements and approved Design have matching `implemented: 2026-10-19` dates;
their approved bodies are unchanged. Temporary multi-phase and phase plans are
removed after validation/Spec promotion; this report retains authority, evidence,
remaining CI risks and exclusions. The new Routine domain and nine owning Specs
are updated; broad generated-client/provider/auth matches do not imply unrelated
behavioral changes.

The assigned single reviewer completed one read-only review of the integrated
34-file phase diff against Phase 4 `eeb9724662b12fd9b03bccf43cd7fa4939325375`,
with **0 actionable findings**. The frozen review patch SHA-256 was
`09aca99f55c6a6b6a7ae37feb0eb9e007118e2e5723f05c1f3903b1c2f56ddd8`.
The reviewer verified preserved focused/required/Web JUnit evidence and whitespace;
root remains the owner of all integrated execution. No code correction or
additional review was required. Subsequent edits only record this review result.

Pending at this pre-commit checkpoint: commit/push and Phase 5 PR/CI. Unresolved
Phase 1/4 duration failures remain explicit blockers to full-stack green.
