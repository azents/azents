---
title: "Failed-run Error Retry and Finalization Design"
created: 2026-06-28
updated: 2026-06-28
tags: [backend, engine, worker, retry, ux]
---
# Failed-run Error Retry and Finalization Design

## Summary

Azents will treat failed-run errors as a run lifecycle concern instead of an immediate transcript append concern. A run-stopping failure first becomes a structured failed attempt, then a bounded retry loop decides whether to continue the same run or promote the latest failure to final durable output.

This design implements the decisions recorded in [ADR-0084: Failed-run Error Retry and Finalization](../adr/0084-failed-run-error-retry.md).

## Goals

- Prevent transient run-stopping failures from immediately appending durable `system_error` events.
- Keep retry progress durable across worker handover and stale running-session recovery.
- Show retry progress in live state without polluting durable chat history.
- Finalize all run-stopping failures through one failed-run finalization policy.
- Prevent Goal continuation from re-entering after failed terminal runs.
- Improve UX so users see retry state and final failure context instead of only repeated red error text.

## Non-goals

- Do not classify every provider-specific error in v1.
- Do not add a per-attempt audit table in v1.
- Do not add a new durable `failed_run_error` event kind in v1.
- Do not change tool-level failed observations that the model can consume and continue from.
- Do not preserve compatibility with scattered legacy finalization behavior once the migration begins.

## Terminology

- **failed-run error**: a failure that stops an active or intended run from continuing and eventually closes the run as failed.
- **tool-level failure**: a tool result or observation with failed status that the model can still consume while the run continues. This is not a failed-run error.
- **attempt failure**: one failed execution attempt inside a run, before retry is exhausted.
- **terminal failure**: the final failed-run state after retries are exhausted or retry is stopped by the user.

## Current Behavior

The current error/finalization behavior is distributed across several layers:

- `worker/run/executor.py` handles resolve failures, user-visible runtime errors, and unexpected exceptions by emitting `system_error`, emitting `RunComplete`, and marking the run terminal.
- `worker/run/command_executor.py` has a similar command-specific failure path.
- `engine/events/execution.py` and `engine/events/engine_adapter.py` can convert engine/runtime failures into durable event output and terminal markers.
- `worker/session/errors.py` reports session runner errors independently of the run finalization path.
- `worker/session/runner.py` triggers idle continuation after terminal run boundaries without requiring durable run success status.

This makes retry unsafe because lower layers can finalize a run before a retry controller has a chance to decide whether the failure is transient.

## Target Architecture

```text
RunExecutor / CommandExecutor / SessionRunner run boundary
  -> FailedRunAttempt boundary
  -> retry state update on agent_runs.retry_state
  -> live run.retry projection
  -> wait until next_retry_at or run next attempt
  -> on success: clear retry state and continue normal completion
  -> on exhausted/stop: FailedRunErrorFinalizer
       -> durable system_error with failed-run metadata
       -> failed run marker where applicable
       -> agent_runs.status = FAILED
       -> RunComplete
       -> live state clear
```

### Component responsibilities

#### `FailedRunAttempt`

A structured value created at the retry boundary from caught exceptions or failure results.

Expected fields:

- `user_message`: user-safe message for live UI and final durable error.
- `internal_message`: optional diagnostic summary for logs only.
- `error_type`: exception class or stable failure type.
- `source`: model, engine, worker, command, session_runner, or resolve boundary.
- `visibility`: user_visible or internal.
- `attempt_number`: failed attempt number.
- `occurred_at`: UTC timestamp.
- future fields: `retryability`, `failure_code`, provider retry hints.

Unexpected exceptions are logged with stack traces at the boundary that converts/finalizes them. Intermediate layers should avoid catch-log-rethrow duplication.

#### `FailedRunRetryState`

A durable JSON-compatible state stored on `agent_runs.retry_state`.

Expected shape:

```json
{
  "schema_version": 1,
  "status": "waiting",
  "failed_attempt_count": 3,
  "max_retries": 10,
  "last_user_message": "An internal error occurred.",
  "last_error_type": "RuntimeError",
  "last_source": "engine",
  "last_failed_at": "2026-06-28T00:00:00Z",
  "backoff_seconds": 4,
  "next_retry_at": "2026-06-28T00:00:04Z",
  "retryability": "unknown",
  "failure_code": null
}
```

The DB payload is JSONB, but application code must validate it through a typed model before use.

#### `RunFailureController` / `FailedRunErrorFinalizer`

The finalizer owns terminal failed-run orchestration. It should be callable from all run-stopping failure paths and must delegate durable event append and terminal `agent_runs` updates to the engine event-store boundary instead of reaching into transcript/run repositories directly.

Responsibilities:

- Build the finalization request from the latest retry state.
- Ask the engine failed-run event store to append the final durable `system_error` event with failed-run metadata.
- Ask the same event-store boundary to append the failed run marker where that marker is part of the run transcript contract.
- Ask the same event-store boundary to mark the `agent_runs` row terminal failed, clearing retry state and active tool calls.
- Emit `RunComplete` through the existing event publishing path.
- Preserve user-safe durable content and log internal details separately.

## Retry Policy

The v1 policy is intentionally uniform for every run-stopping failure:

- initial attempt is not counted as a retry;
- maximum retry count is 10;
- base delay is 1 second;
- multiplier is 2;
- maximum delay is 60 seconds;
- delay after failed attempt N is `min(60s, 1s * 2^(N - 1))`.

Future classification may short-circuit non-retryable failures, honor provider `Retry-After`, or use model/provider-specific policies. v1 keeps those as extension points instead of prerequisites.

## Durable State Changes

### `agent_runs.retry_state`

Add a nullable JSONB column to `agent_runs`.

- `NULL`: no retry is active.
- non-null: the run remains `RUNNING` and is waiting for retry or in retry handling.
- terminal transitions clear the retry state.

Repository changes:

- Extend `RDBAgentRun` with `retry_state`.
- Extend `AgentRunState`, `AgentRunCreate` if needed, and `AgentRunPatch` with typed JSON values.
- Add repository helpers to update/clear retry state atomically.
- Ensure `mark_terminal` and `mark_terminal_if_running` clear retry state.

### `SystemErrorPayload.failure`

Extend `SystemErrorPayload` with optional failed-run metadata:

```json
{
  "kind": "failed_run",
  "finalization_reason": "retry_exhausted",
  "failed_attempt_count": 10,
  "max_retries": 10,
  "last_error_type": "RuntimeError",
  "retryability": "unknown",
  "failure_code": null,
  "action_hint": null
}
```

The metadata must remain user-safe. Stack traces, raw provider response bodies, credential details, and billing-provider raw responses must stay in logs/observability only.

## Live State Changes

`ChatLiveRunState` gains an optional `retry` field derived from `agent_runs.retry_state`.

Expected API shape:

```json
{
  "run_id": "...",
  "phase": "running",
  "status": "running",
  "retry": {
    "status": "waiting",
    "last_error_message": "An internal error occurred.",
    "failed_attempt_count": 3,
    "max_retries": 10,
    "backoff_seconds": 4,
    "next_retry_at": "2026-06-28T00:00:04Z"
  }
}
```

The server should publish retry live updates only when retry state changes. It does not need to push per-second countdown ticks. Clients calculate remaining time from `next_retry_at`.

## Handover and Stale Recovery

When a worker reacquires a running session with retry state:

1. Load the running `agent_runs` row.
2. Validate `retry_state`.
3. Re-publish the live run retry projection.
4. If `now < next_retry_at`, wait until that timestamp while honoring stop and shutdown signals.
5. If `now >= next_retry_at`, start the next attempt immediately.
6. Preserve the retry count and do not reset the retry budget.

Worker restart must not bypass exponential backoff. Shutdown during retry wait should leave the run running so another worker can repeat the same durable resume logic.

## Stop During Retry

A stop request while retry is active means "stop retrying" in v1.

The latest failed attempt is promoted to final durable failed-run output with `finalization_reason = "retry_stopped_by_user"`. The terminal event is `RunComplete`, not `RunStopped`, because the run outcome is failed after retry finalization.

The UI should label this action as "Stop retrying" / "재시도 중지" while retry is active.

## Goal Continuation Gating

Goal continuation is allowed only after a durable run terminal status of `COMPLETED`.

The idle continuation path must not rely on the presence of `RunComplete` alone, because failed-run finalization also ends with `RunComplete`. The idle boundary should carry or query the latest relevant `agent_runs.status` and call the goal continuation hook only when it is `COMPLETED`.

Blocked statuses:

- `FAILED`
- `STOPPED`
- `CANCELLED`
- `INTERRUPTED`
- retry-active `RUNNING`

This makes retry responsible for recovering failed attempts and Goal continuation responsible only for continuing after successful progress.

## Migration Plan

### Phase 0: finalization unification foundation

- Add typed failed-run attempt and retry-state models.
- Add `agent_runs.retry_state` migration and repository accessors.
- Add failed-run metadata to `SystemErrorPayload`.
- Introduce the shared finalizer/controller without enabling retry yet.
- Route existing run-stopping failure paths through the finalizer where possible.
- Gate Goal continuation on durable `COMPLETED` status.

### Phase 1: retry loop

- Wrap `RunExecutor` attempt execution with retry handling.
- Convert caught exceptions/failures into `FailedRunAttempt`.
- Persist retry state and project it to live run state.
- Honor stop/shutdown during retry wait.
- Preserve durable history until terminal failure.

### Phase 2: command and session-runner convergence

- Route command failures through the same finalizer/retry controller.
- Route session runner run-stopping failures through the same finalizer when they terminate run progress.
- Keep message-processing errors that do not represent a run-stopping failure outside the failed-run scope.

### Phase 3: UX recovery improvements

- Render retry countdown and latest error in live run activity.
- Render final failed-run metadata in the history error card.
- Add user-safe action hints.
- Consider explicit separate actions for generic stop vs stop retrying.

### Phase 4: classification improvements

- Add `retryability` classification for known non-retryable failures.
- Honor provider `Retry-After` where available.
- Add provider/model-specific policy overrides if needed.

## Feasibility Check

### Feasible with current storage model

`agent_runs` already stores JSONB `active_tool_calls`, lifecycle timestamps, status, phase, and stop request timestamps. Adding nullable JSONB `retry_state` fits the current model and keeps retry state attached to the run row.

`AgentRunRepository.update()` already supports partial run patches, and terminal helpers already centralize status/phase/active-tool cleanup. Extending these helpers to clear retry state is straightforward.

### Feasible with current live-state model

`ChatLiveRunState` is already built from the current running `agent_runs` row in `ChatService.list_live_events()`. Adding an optional retry field is a small service/API model extension. Redis live event projection can remain responsible for partial transcript/live events; retry state belongs to the run snapshot rather than the event list.

### Feasible with current worker ownership model

`SessionRunner` already owns session wake-up processing, stop detection, shutdown detection, and handover wake-up. `RunExecutor` already owns the normal run boundary and run heartbeat loop. A retry wait can honor the same `check_stop`/shutdown signals and leave the run `RUNNING` for handover.

### Requires careful refactor

The main risk is existing lower layers that already append durable errors or terminal markers. The implementation must prevent double-finalization by ensuring retryable attempt failures bubble to the retry boundary before durable output is appended.

High-risk files:

- `engine/events/execution.py`
- `engine/events/engine_adapter.py`
- `worker/run/executor.py`
- `worker/run/command_executor.py`
- `worker/session/errors.py`
- `worker/session/runner.py`

### Goal continuation is feasible but needs run status at idle boundary

`IdleContinuationService.enqueue()` currently passes `reason="completed"` without validating durable run status. `SessionRunner` has the run id in the terminal boundary, and `AgentRunRepository` can fetch the run status. The idle boundary should either carry terminal status from `RunExecutionResult` or query it before dispatching idle hooks.

### API compatibility impact

Adding optional fields is additive for API responses and event payloads. Existing clients that ignore unknown fields should continue working. UI changes are still required to show retry status and final failed-run metadata.

### Open implementation risks

- `RunComplete` is currently used as a terminal stream boundary for both success and failure. Code must not infer success from this event.
- Resolve failures may happen before a run projection is created. The implementation should create or identify a run row before retry/finalization when the failure stops intended run progress.
- Shutdown during retry wait must preserve running state for handover instead of accidentally finalizing.
- Logging must avoid both missing stack traces and duplicated exception logs.

## Test Strategy

### E2E primary verification matrix

E2E should be the primary product-behavior verification surface.

Scenarios:

1. **Transient model failure recovers**
   - Inject one or more model/engine failures, then succeed.
   - Verify no durable `system_error` is appended during retry.
   - Verify live run state shows retry countdown.
   - Verify final run status is `COMPLETED` and Goal continuation can run if active.

2. **Retry exhausted**
   - Inject persistent run-stopping failure.
   - Verify retry state reaches max retries.
   - Verify one final durable `system_error` with failed-run metadata.
   - Verify final run status is `FAILED`.
   - Verify no `goal_continuation` is enqueued.

3. **Stop during retry**
   - Trigger retry wait, then stop retrying.
   - Verify latest error is promoted to durable failed-run output.
   - Verify `finalization_reason = retry_stopped_by_user`.
   - Verify terminal boundary is `RunComplete`, final status is `FAILED`, and Goal continuation is blocked.

4. **Worker handover during retry wait**
   - Trigger retry wait, stop/restart or hand over worker ownership.
   - Verify retry count and `next_retry_at` are preserved.
   - Verify the new worker does not bypass backoff.
   - Verify retry eventually continues from the same durable state.

5. **Tool-level failed observation is not retried as failed-run error**
   - Produce a failed tool result that the model can observe.
   - Verify the run continues and no failed-run retry state is created.

6. **Command failure convergence**
   - Trigger command path failure.
   - Verify finalization shape matches normal run failed-run output.

### E2E plan

- Add deterministic failure injection for model/engine execution in the test environment.
- Use WebSocket/live snapshot assertions for `run.retry`.
- Use REST history assertions for absence/presence of durable `system_error`.
- Use DB assertions only where needed for `agent_runs.retry_state`, final status, and handover persistence.

### Testenv support

Testenv support is needed for deterministic model/engine failure injection and worker handover simulation. E2E remains primary; testenv is the controlled fixture layer used by E2E.

Required fixture support:

- model adapter or engine test hook that fails N attempts then succeeds;
- persistent failure fixture;
- retry wait with configurable shorter delays for tests;
- worker handover/restart helper;
- active goal fixture.

### Unit/integration tests

- Retry policy delay calculation.
- Failed attempt conversion and logging behavior.
- Retry state validation/serialization.
- `AgentRunRepository` retry state update/clear helpers.
- `SystemErrorPayload` failed-run metadata validation.
- Goal continuation gating by terminal run status.
- Finalizer idempotency around terminal run updates and event append.

### Evidence format

- E2E run output with scenario names.
- Captured live snapshot showing `run.retry` during retry.
- Captured final history event showing failed-run metadata.
- DB assertion logs or test assertions for `agent_runs.status` and `retry_state`.

### CI execution policy

- Unit and integration tests should run in regular CI.
- E2E retry tests should run in CI when deterministic failure fixtures are available.
- Worker handover E2E may be marked optional initially if CI cannot reliably restart workers, but it must be run before release as a required manual or nightly check.

### Skip/fail criteria

- Skip optional live/provider tests only when external credentials or provider availability are missing.
- Do not skip deterministic retry E2E tests once fixtures are available.
- Any durable `system_error` emitted before retry exhaustion is a failure.
- Any Goal continuation after final `FAILED` status is a failure.
