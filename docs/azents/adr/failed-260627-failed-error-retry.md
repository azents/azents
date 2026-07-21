---
title: "Failed-run Error Retry and Finalization"
created: 2026-06-27
tags: [architecture, backend, engine, worker, retry, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: failed-260627
historical_reconstruction: true
migration_source: "docs/azents/adr/0084-failed-run-error-retry.md"
---
# failed-260627/ADR: Failed-run Error Retry and Finalization

## Context

Azents currently treats many failed-run errors as terminal immediately. A model call failure, empty model output, engine/runtime exception, or command failure can append a durable `system_error`, mark `agent_runs.status` as `FAILED`, and emit `RunComplete` before any retry policy can decide whether the failure was transient.

This causes three product problems:

- Goal continuation can repeatedly resume after unrecoverable failed-run errors and pollute context with repeated continuation/error events.
- Transient failed-run errors are exposed as final user-visible errors without a bounded automatic retry window.
- The UI mostly shows a red error text instead of live retry state, recovery affordances, or next action guidance.

The current failed-run finalization logic is also split across multiple boundaries, including `AgentRunExecution`, `AgentEngineAdapter`, `RunExecutor`, `CommandExecutor`, and `SessionRunnerErrorReporter`. Retry requires first separating attempt failure from terminal failed-run finalization.

## Decision

### [file-260628/ADR-D1](./file-260628-file-management.md). Use a shared failed-run finalizer with RunExecutor-centered ownership

Azents will consolidate failed-run finalization behind a shared component, such as `FailedRunErrorFinalizer` or `RunFailureController`.

The shared component owns the final failed-run policy and durable finalization shape, including:

- durable `system_error` creation;
- failed terminal run marker creation where applicable;
- `agent_runs.status = FAILED` transition;
- terminal `RunComplete` publication;
- final failure metadata needed by future retry and UI recovery work.

For normal chat runs, the worker run boundary, especially `RunExecutor`, is the primary caller/owner of failed-run finalization. Command execution should eventually use the same shared component so command failures and normal run failures have one finalization policy.

Lower engine layers should not independently turn retryable attempt failures into durable terminal failed-run output before the retry/finalization boundary can handle them.

### [file-260628/ADR-D2](./file-260628-file-management.md). Convert exceptions to structured failed attempts at the retry boundary

Azents will use a hybrid attempt failure model.

Lower layers may continue to use exception flow for attempt failures, but the retry boundary converts caught exceptions into a structured failed attempt value, such as `FailedRunAttempt`. Retry and finalization logic consume the structured failed attempt rather than raw exceptions.

A structured failed attempt must preserve enough information for retry state, final durable output, and observability, including:

- user-visible message for UI and final durable error;
- internal error type/class;
- source or boundary where the failure happened, such as model, engine, worker, or command;
- stack trace/log context for unexpected exceptions;
- attempt number and occurrence time when retry is active.

Exception conversion must handle logging carefully. The boundary that handles or finalizes the exception is responsible for logging. Intermediate layers must avoid duplicate catch-log-rethrow patterns. Unexpected exceptions must keep stack traces in logs, while durable `system_error` content remains user-safe.

Retry-in-progress attempt failures must not prematurely append durable `system_error`, append failed `run_marker`, mark `agent_runs.status = FAILED`, or emit `RunComplete`.

### [file-260628/ADR-D3](./file-260628-file-management.md). Treat every run-stopping failure as failed-run finalization scope

The failed-run error retry/finalization scope includes every failure that stops an active or intended run from continuing.

The policy is not limited to model-call failures. It applies to all run-stopping failures, including normal chat run failures, command run failures, run preparation/resolve failures, toolkit/catalog construction failures, worker-boundary execution failures, and session runner failures when they terminate run progress.

Tool-level observations that do not stop the run remain outside this scope. For example, a `client_tool_result(status="failed")` that is returned to the model and allows the run to continue is not a failed-run error.

This decision means implementation may still migrate call sites in phases, but the target architecture has one failed-run finalization policy for all run-stopping failures.

### [file-260628/ADR-D4](./file-260628-file-management.md). Store retry state on `agent_runs` and project it to live state

Retry state is part of the durable run lifecycle. Azents will store the retry source of truth on the `agent_runs` row, initially as a structured JSON payload such as `retry_state`.

The retry state includes at least:

- latest failed attempt summary, including user-safe error message and internal error type;
- failed attempt count and maximum retries;
- current retry phase, such as waiting/backing off;
- backoff seconds and `next_retry_at`;
- timestamps for the latest failure and retry scheduling.

Live state is a projection of this durable run retry state, not the source of truth. UI countdowns and retry banners are driven by live state, but worker handover and stale recovery resume from `agent_runs.retry_state`.

This preserves retry progress across worker handover, process restarts, and stale running-session recovery. A worker that reacquires a running session reads the current retry state, republishes the live projection, waits until `next_retry_at` when necessary, and continues the same retry sequence instead of restarting the retry budget.

### [file-260628/ADR-D5](./file-260628-file-management.md). Expose retry status as part of the live run state

Retry is current run activity, not durable chat history. Azents will expose retry status through the existing live run state instead of appending retry attempts to the durable transcript.

The live run state gains an optional retry field derived from `agent_runs.retry_state`. It includes at least:

- retry status, such as waiting/backing off;
- last user-safe error message;
- failed attempt count and maximum retries;
- backoff seconds;
- `next_retry_at` as an absolute timestamp.

The UI displays retry banners and countdowns from this live run retry state. The server does not need to push per-second countdown events; clients calculate remaining time from `next_retry_at`.

When retry succeeds, retry live state is cleared and the run proceeds normally. When retries are exhausted or stopped, the final failure is promoted to durable history as a `system_error`, the run is finalized as failed, and the live run state is cleared through the normal terminal run boundary.

### [file-260628/ADR-D6](./file-260628-file-management.md). Apply one v1 retry policy to all run-stopping failures

The first retry implementation applies the same bounded retry policy to every run-stopping failure in the failed-run error scope.

The v1 policy is:

- initial attempt is not counted as a retry;
- maximum retry count is 10;
- base delay is 1 second;
- multiplier is 2;
- maximum delay is 60 seconds;
- delay after failed attempt N is `min(60s, 1s * 2^(N - 1))`, where N is the failed attempt count that just occurred.

This intentionally retries failures that may later become classified as non-retryable, such as subscription usage, billing, permission, or credential failures. The initial goal is to prevent premature durable finalization and recover transient failures without introducing provider-specific error classification as a prerequisite.

The structured failed attempt and retry state must still leave room for future classification fields such as `retryability` or `failure_code`. A later design may short-circuit known non-retryable failures, honor provider `Retry-After`, or apply provider/model-specific policies without changing the core failed-run finalization model.

### [file-260628/ADR-D7](./file-260628-file-management.md). Resume retry after handover by honoring `next_retry_at`

Worker handover, process restart, and stale running-session recovery must continue the same retry sequence instead of resetting the retry budget or immediately finalizing the run.

When a worker reacquires a running session with `agent_runs.retry_state`:

- it republishes the retry live run state from the durable retry state;
- it preserves the failed attempt count and maximum retry count;
- if the current time is before `next_retry_at`, it waits until `next_retry_at` while still honoring stop and shutdown signals;
- if the current time is at or after `next_retry_at`, it starts the next attempt immediately;
- if the worker shuts down during the wait, it leaves the run running so the next worker can repeat the same durable resume logic.

Worker restart must not become a way to bypass exponential backoff. Stale recovery must also not emit durable `system_error`, failed run marker, or `RunComplete` merely because retry state exists. Final durable failure is emitted only when retry is exhausted or explicitly stopped according to the failed-run finalization policy.

### [file-260628/ADR-D8](./file-260628-file-management.md). Stopping during retry promotes the latest error to final failed-run output

When the user stops a run while it is waiting to retry or otherwise inside retry handling, Azents treats the action as stopping retry, not as a normal successful interruption.

The latest structured failed attempt is promoted to final durable failed-run output:

- append durable `system_error` from the latest user-safe error message;
- append failed run marker where applicable;
- mark `agent_runs.status = FAILED`;
- clear retry live state through the terminal run boundary;
- emit `RunComplete` rather than `RunStopped`;
- prevent Goal continuation from running for that failed terminal run.

The finalization metadata should record that the failure was finalized because retry was stopped by the user, for example `finalization_reason = "retry_stopped_by_user"`.

The UI should label this action as stopping retry, such as "Stop retrying" or "재시도 중지", instead of presenting it as a generic run stop. A future design may split generic stop and stop-retrying into separate user actions, but v1 uses stop-during-retry as failed-run finalization.

### [file-260628/ADR-D9](./file-260628-file-management.md). Goal continuation runs only after successful run completion

Goal continuation is allowed only after a terminal run whose durable status is `COMPLETED`.

Goal continuation must not be triggered merely because the stream emitted `RunComplete`. Failed-run errors also end with `RunComplete` after finalization, so the idle continuation decision must read the durable run terminal status, not only the stream boundary event.

Goal continuation is blocked when the latest relevant run status is any non-success terminal state, including:

- `FAILED`;
- `STOPPED`;
- `CANCELLED`;
- `INTERRUPTED`.

Goal continuation is also blocked while retry is in progress because the run remains `RUNNING` and the session must not transition through the normal idle continuation path.

This makes retry responsible for recovering failed attempts, while Goal continuation is responsible only for pursuing active goals after successful progress. Retry exhaustion or stop-during-retry therefore does not enqueue a new `goal_continuation` input and does not pollute context with repeated continuation/error cycles.

### [file-260628/ADR-D10](./file-260628-file-management.md). Extend `system_error` with failed-run metadata

Final failed-run output remains a durable `system_error` event. Azents will extend `SystemErrorPayload` with optional failed-run metadata instead of introducing a new failed-run event kind.

The durable `system_error.content` remains the user-safe error message. Retry and finalization context is stored in structured metadata, for example:

- `kind = "failed_run"`;
- `finalization_reason`, such as `retry_exhausted` or `retry_stopped_by_user`;
- failed attempt count;
- maximum retry count;
- last user-safe error type or class name;
- future classification fields such as `retryability` or `failure_code`;
- optional user-facing `action_hint`.

The metadata must remain user-safe. Stack traces, raw provider response bodies, credential details, and other internal diagnostic payloads belong in logs or observability systems, not durable transcript history.

This keeps `system_error` as the canonical durable UI error event while allowing the UI to distinguish a plain system error from a retry-exhausted failed-run error and render recovery-oriented error cards instead of a red text-only message.

## Consequences

### Positive

- Retry can run before a failed-run error becomes durable history.
- The final failed-run shape becomes consistent across user-visible, internal, and command failures.
- Goal continuation can distinguish successful terminal runs from failed terminal runs.
- Observability improves because attempt failures become structured while stack traces remain available for unexpected errors.

### Negative / trade-offs

- Failed-run handling needs a Phase 0 refactor before retry can be added safely.
- Existing tests that expect immediate durable `system_error`, failed run marker, or `RunComplete` may need to move to the finalization boundary.
- The transition must avoid double-finalization while old paths are being migrated.

## Alternatives

### Keep finalization in existing layers

Rejected. Retry would still race with lower layers that already append durable errors, mark runs failed, or emit `RunComplete`.

### Make `AgentEngineAdapter` the only finalization owner

Rejected for now. It is close to transcript handling but does not naturally own worker boundary failures, command failures, live retry state, or handover behavior.

### Replace exception flow with result objects everywhere

Rejected for the initial design. A full result-object rewrite would be large and would not align with the current async iterator and exception-based engine flow. The hybrid boundary conversion gives retry a structured model without rewriting the whole engine.

## Related documents

- [Agent Execution Loop](../spec/flow/agent-execution-loop.md)
- [execution-260527/ADR: Agent Execution Transcript Normalization](./execution-260527-execution-transcript-normalization.md)
- [goal-260615/ADR: Goal Continuation Idle Hook](./goal-260615-goal-continuation-idle-hook.md)

## Migration provenance

- Historical source filename: `0084-failed-run-error-retry.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
