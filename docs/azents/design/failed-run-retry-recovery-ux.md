---
title: "Failed-run Retry Recovery UX"
created: 2026-07-05
implemented: 2026-07-05
tags: [backend, frontend, api, chat, retry, ux]
---
# Failed-run Retry Recovery UX

## Problem

The failed-run retry implementation persists retry state and eventually renders a terminal failed-run error, but the user-facing recovery flow is incomplete.

Observed issues:

1. While automatic retry is in progress, the chat timeline does not show a live error/retry card. Users only see the final card after the retry budget is exhausted.
2. The terminal error message is rendered as standalone red monospace text separate from the failed-run summary card. The error message should be card content.
3. After retry exhaustion, there is no user action to start another retry cycle.

## Goals

- Show a live retry card immediately after the first failed attempt.
- Keep the card updated with the latest user-safe error message.
- Show a client-side countdown until `next_retry_at` while waiting.
- Show the existing LLM call dots indicator when the retry attempt is actively waiting for or streaming a model response.
- Let users expand the card to inspect the user-safe failed-attempt history.
- Render terminal failed-run errors as one coherent card, with the error message inside the card.
- Provide a manual retry action after automatic retry exhaustion.
- When manual retry starts, remove the terminal failed card from the visible latest transcript and re-enter the normal run loop with a fresh retry budget.

## Non-goals

- Do not add provider-specific retry classification in this change.
- Do not expose internal stack traces, raw credentials, or observability-only diagnostics in UI payloads.
- Do not make tool-level failed observations use failed-run retry UI.
- Do not change the v1 automatic retry budget or backoff policy.
- Do not add model-visible retry pseudo-tools.

## Current Behavior and Findings

### Backend

Relevant paths:

- `python/apps/azents/src/azents/worker/run/executor.py`
- `python/apps/azents/src/azents/engine/run/failure.py`
- `python/apps/azents/src/azents/services/chat/__init__.py`
- `python/apps/azents/src/azents/api/public/chat/v1/data.py`
- `python/apps/azents/src/azents/worker/live/event_projector.py`
- `python/apps/azents/src/azents/worker/session/lifecycle.py`

Current implementation already has the durable foundation from ADR-0084:

- `FailedRunRetryState` is stored on `agent_runs.retry_state`.
- `GET /chat/v1/sessions/{session_id}/live` projects `run.retry` when the current running run has retry state.
- Terminal failed-run finalization appends a durable `system_error` with `failure.kind = "failed_run"` metadata.

Gaps:

- Retry state updates only change the DB row and Redis session activity. They do not publish a semantic WebSocket update for the current live run snapshot.
- `SessionActivity` only stores `run_id`, `phase`, and `active_tool_calls`; it does not carry retry information.
- `LiveEventProjector` only manages partial-history live events. It does not publish non-partial run-state updates.
- `FailedRunRetryState` stores only the latest failed attempt summary. It cannot support an expandable attempt history card.
- There is no public API for retrying a terminal failed run.

### Frontend

Relevant paths:

- `typescript/apps/azents-web/src/features/chat/types.ts`
- `typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts`
- `typescript/apps/azents-web/src/features/chat/components/ChatView.tsx`
- `typescript/apps/azents-web/src/features/chat/components/MessageBubble.tsx`
- `typescript/apps/azents-web/src/features/chat/components/AgentRunIndicator.tsx`

Gaps:

- `ChatLiveRunState` in frontend types does not include `retry`, even though backend response includes it.
- `ManagedLiveState` stores only `liveRunPhase`, `isResponsePending`, `isModelResponsePending`, and similar booleans. It discards `run.retry` from `/live` snapshots.
- WebSocket handling updates run state from legacy `run_started`, `run_phase_changed`, and terminal events, but there is no reducer path for `run.retry` updates.
- Final failed-run metadata is mapped into message metadata, but `ErrorTextMessage` renders the raw message text and the recovery summary as visually separate areas.
- No retry action prop is available from the container to the terminal failed-run card.

## Accepted Decisions

### Manual retry removes the terminal failed card through soft-revert

Accepted on 2026-07-05. Manual retry uses the existing reverted-event mechanism to hide the terminal failed-run output from the latest visible transcript and then re-enters the normal run loop. This matches the product expectation that accepting retry clears the failed card instead of leaving the session visually failed while a new run is active.

Manual retry is allowed only when the failed-run error card is the latest visible durable event. If any visible durable event exists after the failed-run `system_error`, the retry action must be unavailable or rejected with conflict, because the user-visible transcript has moved on and soft-reverting from that older failure would discard newer context.

Rejected alternatives:

- Keeping the failed card and appending a separate retry-started message, because the UI would continue to look failed during an active retry.
- Adding a synthetic user message, because it changes the model-visible task semantics and turns retry into a new user instruction.

## Proposed Design

### 1. Treat failed-run retry UI as live run control state

Automatic retry-in-progress UI is not durable chat history. It belongs to other live state, consistent with ADR-0054.

Add a frontend `RunRetryCard` rendered near the latest timeline tail when:

- `chatTimelineState.type === "LATEST_FOLLOWING"`, and
- `managedLiveState.liveRun?.retry` is present.

The card shows:

- latest error message inside the card;
- failed attempt count and max retry count;
- countdown until `next_retry_at` when the run is waiting;
- an expandable attempt history list;
- a stop-retrying affordance through the existing stop action, labelled as retry stop in UI copy when retry is active.

When the active run phase is `waiting_for_model` or `streaming_model` and retry state is present, keep the card visible and render `AgentRunIndicator` below it. This reuses the existing dots indicator rather than creating a second animation.

### 2. Publish live run updates over WebSocket

Add semantic WebSocket actions for run live state:

```json
{
  "type": "live_run_updated",
  "session_id": "...",
  "run": {
    "run_id": "...",
    "phase": "waiting_for_model",
    "status": "running",
    "retry": {
      "status": "waiting",
      "last_error_message": "An internal error occurred.",
      "failed_attempt_count": 3,
      "max_retries": 10,
      "backoff_seconds": 4,
      "next_retry_at": "2026-07-05T00:00:04Z",
      "attempts": []
    }
  }
}
```

```json
{
  "type": "live_run_cleared",
  "session_id": "..."
}
```

Publication points:

- after run projection creation / `RunStarted`;
- after each `RunPhaseChanged`;
- after `_record_failed_run_attempt()` updates `agent_runs.retry_state`;
- when retry wait resumes from handover and republishes current state;
- when terminal finalization clears the run;
- when session activity is cleared after normal terminal completion.

The REST `/live` snapshot remains the reconnect source of truth. WebSocket updates are patches to the same managed live state object.

### 3. Preserve failed-attempt history in retry state

Extend `FailedRunRetryState` with bounded user-safe attempt summaries:

```json
{
  "attempts": [
    {
      "attempt_number": 1,
      "user_message": "Model call failed (429): ...",
      "error_type": "RateLimitError",
      "source": "model",
      "failed_at": "2026-07-05T00:00:00Z",
      "backoff_seconds": 1,
      "next_retry_at": "2026-07-05T00:00:01Z",
      "retryability": "unknown",
      "failure_code": null
    }
  ]
}
```

Rules:

- Store only user-safe messages already allowed for live UI.
- Cap each stored message to a safe display length, with truncation metadata if needed.
- Keep at most the configured retry budget count.
- When creating a new retry state from an attempt, append the new summary to the previous state's `attempts` list.
- Include the same attempt summaries in terminal failed-run metadata so the final card can expand history after retry exhaustion.

### 4. Render terminal failed-run errors as a single card

Replace the current terminal failed-run rendering with one `FailedRunErrorCard` component.

For `message.role === "error"` and `message.metadata.failed_run_kind === "failed_run"`:

- render a card with title, retry/finalization summary, and the error message inside the card;
- use monospace only for the error message block;
- use smaller card-body text sizing than the current red standalone message;
- clamp long error messages by default and allow expansion;
- render attempt history inside the same expandable card area;
- show a manual retry button when finalization reason is retry exhaustion or retry stopped by user and a retry action is available.

For non-failed-run `system_error` messages, keep a simple error card, but still avoid standalone raw red text outside the card.

### 5. Manual retry of exhausted failed runs

Add a public REST action:

```http
POST /chat/v1/sessions/{session_id}/retry-failed-run
```

Request:

```json
{
  "agent_id": "...",
  "failed_event_id": "...",
  "client_request_id": "..."
}
```

Response: reuse the chat write response shape, extending accepted type with `failed_run_retry`.

Behavior:

1. Validate session access and agent/session match.
2. Require the session to be idle and have no pending command/input buffer.
3. Load `failed_event_id` and verify it is a visible `system_error` in the session with `failure.kind = "failed_run"`.
4. Verify it is the latest visible durable event in the session. A failed-run error with any later visible durable event is stale and must fail with conflict.
5. Create an idempotency record with write type `failed_run_retry`.
6. Soft-revert durable events from the failed terminal error event's `model_order` onward using the existing reverted-event mechanism.
   - This removes the terminal failed card and failed run marker from normal latest history reads.
   - It preserves the pre-failure transcript tail so the normal execution loop has actionable model input again.
7. Clear pending input buffers for the session as a safety invariant.
8. Mark the session running and send the existing `SessionWakeUp` broker message.
9. Return a snapshot with `history_reload_required = true` so the frontend reloads history and the card disappears immediately.

This intentionally re-enters the normal run loop instead of adding a special retry loop outside `RunExecutor`. The new run receives a fresh retry budget because it creates a new `agent_runs` row.

### 6. Frontend state model

Extend frontend types:

- `ChatLiveRunRetryAttempt`
- `ChatLiveRunRetryState`
- `ChatLiveRunState.retry`
- `ManagedLiveState.liveRun`

Derive existing booleans from `liveRun`:

- `liveRunPhase = liveRun?.phase ?? null`
- `isResponsePending = liveRun != null || partialHistory has items || pending input exists`
- `isModelResponsePending = isModelRunPhase(liveRun?.phase ?? null)`
- `retryActive = liveRun?.retry != null`

This prevents losing retry data while preserving existing call sites during component migration.

### 7. Countdown behavior

The backend sends only absolute timestamps. The frontend owns countdown ticking:

- Calculate `remaining = max(0, next_retry_at - now)`.
- Update once per second while the retry card is mounted and waiting.
- Stop ticking when retry disappears, the phase enters model call, or the card unmounts.
- Do not request per-second WebSocket events from the server.

### 8. UI placement

Latest-following timeline tail order:

1. durable history messages;
2. partial history messages;
3. authorization request bubbles;
4. live failed-run retry card, if present;
5. LLM dots indicator when retry card exists and the current phase is model call;
6. normal LLM dots indicator when there is model activity and no visible retry card;
7. compaction indicator;
8. pending input buffers;
9. initialization card.

This order makes retry state visible near the active work without making it durable chat history.

## API and Data Model Changes

### Backend domain models

- Extend `FailedRunRetryState` with `attempts`.
- Add a small typed `FailedRunAttemptSummary` model.
- Extend `FailedRunFailureMetadata` with optional `attempts`.
- Extend `ChatLiveRunRetryState` and response models with `attempts`.
- Add WebSocket payload models/dump helpers for `live_run_updated` and `live_run_cleared`.
- Add `ChatFailedRunRetryRequest`.
- Extend `ChatWriteAcceptedResponse.type` with `failed_run_retry`.
- Add `ChatWriteRequestType.FAILED_RUN_RETRY`.

### Backend services

- Add a failed-run retry service method under the chat write/control boundary.
- Reuse the session idle lock and idempotency pattern from edit/command writes.
- Use the message repository's reverted-event mechanism to remove failed terminal output from visible history.
- Send the standard `SessionWakeUp` after marking the session running.

### Frontend

- Regenerate the public TypeScript client after OpenAPI changes.
- Add retry live-state reducers for REST snapshot and WebSocket actions.
- Add `RunRetryCard` and `FailedRunErrorCard` stories for waiting, calling, expanded history, exhausted, non-retryable, and manual retry pending states.
- Route terminal failed-run messages to `FailedRunErrorCard` instead of `ErrorTextMessage` raw rendering.
- Add tRPC mutation wrapper for `retryFailedRun` using the generated public client.

## Error Handling

- If manual retry is requested for a stale failed event, including any failed-run error that is not the latest visible durable event, return `409 Conflict`.
- If the session is running, return `409 Conflict`.
- If the failed event does not belong to the requester-accessible session, return `404 Not Found`.
- If the failed event is not a failed-run `system_error`, return `409 Conflict`.
- If soft-revert succeeds but broker wake-up fails, the session remains recoverably running and normal broker retry/recovery paths should pick it up. The API should not disguise the broker failure as success if the wake-up cannot be enqueued in the request path.
- Manual retry does not run model work inside the HTTP request.

## Security and Privacy

- The retry card and attempt history must use only user-safe failed attempt fields.
- Internal stack traces and raw internal diagnostics stay in logs.
- Error message rendering must preserve text but avoid making long provider JSON dominate the mobile UI.
- The retry endpoint requires the same session access validation as other chat writes.
- `failed_event_id` prevents a stale UI from accidentally retrying a newer failed run.

## Migration and Rollout

1. Backend live run WebSocket actions and attempt-history payloads.
2. Frontend live retry card using REST snapshot and WebSocket updates.
3. Terminal failed-run card replacement.
4. Manual retry endpoint and frontend button.
5. Spec updates for `agent-execution-loop.md` and the public chat API flow.
6. OpenAPI and generated client regeneration.

## Required Spec Updates for Implementation PRs

This design PR does not update living specs directly because it does not change current product behavior. The implementation PR must update the current-behavior specs after the code lands.

Required spec updates:

- `docs/azents/spec/flow/agent-execution-loop.md`
  - Extend the `run.retry` live projection to include bounded attempt history.
  - Document that retry state changes publish semantic live-run updates, not durable retry-attempt transcript events.
  - Document terminal failed-run card metadata fields used by UI recovery.
  - Document manual retry as an idle-only control action that is allowed only when the failed-run error card is the latest visible durable event.
  - Document that accepted manual retry soft-reverts the terminal failed-run output and re-enters the normal run loop without adding a synthetic user message.
- Public chat API/OpenAPI spec
  - Add the failed-run retry endpoint.
  - Add the `failed_run_retry` accepted write response type.
  - Add live-run WebSocket update/clear actions if those are represented in the public schema.
- Frontend chat/live-state behavior spec, if split from `agent-execution-loop.md` before implementation
  - Document live retry card rendering, countdown behavior, LLM indicator placement during retry attempts, expandable attempt history, and terminal failed-run card retry action availability.

## Alternatives Considered

### Wait until retry exhaustion and only show a final card

Rejected. This is the current broken UX and hides important runtime state.

### Append retry attempts as durable chat messages

Rejected. Retry attempts are live run state, not transcript history. Durable retry-attempt messages would pollute model input and conflict with ADR-0084.

### Keep the terminal failed card and append a "retry started" message

Rejected. The user expectation is that pressing retry removes the terminal failure state and returns to the normal loop. Keeping the failed card visible would make the run look failed while it is active again.

### Retry the failed run by adding a synthetic user message

Rejected. This would make the model see a new user-authored retry instruction and can change task semantics. The retry action should re-open the actionable transcript tail, not add new task content.

### Reuse only legacy `run_phase_changed` WebSocket events

Rejected. Retry is structured live run state. A semantic live-run patch keeps REST and WebSocket reducers aligned and avoids hiding `run.retry` behind phase-only events.

## Test Strategy

### E2E primary verification matrix

1. **Retry card appears immediately**
   - Inject a deterministic model failure.
   - Verify the live retry card appears after the first failed attempt, before retry exhaustion.
   - Verify no durable terminal `system_error` appears during automatic retry.

2. **Latest error and countdown update**
   - Inject multiple failures with different messages.
   - Verify the card shows the newest message and attempt count.
   - Verify the countdown uses `next_retry_at` and decreases client-side.

3. **LLM indicator during retry attempt**
   - During the next retry model call, verify the retry card remains visible and the dots indicator appears below it.

4. **Expandable history**
   - After several failed attempts, expand the card.
   - Verify each user-safe attempt summary is listed in order.

5. **Retry exhausted final card**
   - Exhaust the retry budget.
   - Verify a single terminal failed-run card appears.
   - Verify the error message is inside the card and no standalone red raw error text is rendered outside it.

6. **Manual retry starts normal loop**
   - Click retry on the exhausted card.
   - Verify history reload removes the failed card from latest view.
   - Verify session becomes running and a new run starts with a fresh automatic retry budget.

7. **Manual retry stale event conflict**
   - Attempt retry with an old failed event id after any newer visible durable event has been appended.
   - Verify `409 Conflict` and no history rewrite.

8. **Reconnect during retry**
   - Refresh or reconnect while retry is waiting.
   - Verify `/live` snapshot restores the retry card and countdown.

### Testenv support

Testenv should provide deterministic failed-run fixtures:

- fail N model calls then succeed;
- always fail until retry exhaustion;
- fail with distinct messages per attempt;
- optionally shorten backoff for deterministic E2E.

### Unit and integration tests

Backend:

- `FailedRunRetryState` appends and serializes attempt summaries.
- `/live` response includes retry attempts.
- `live_run_updated` is published when retry state changes.
- manual retry validates failed event shape and latest-tail status.
- manual retry soft-reverts failed terminal output and wakes the session.
- manual retry idempotency returns the same accepted result for the same `client_request_id`.

Frontend:

- live snapshot reducer preserves `run.retry`.
- WebSocket `live_run_updated` and `live_run_cleared` mutate managed live state.
- countdown hook calculates remaining time from `next_retry_at`.
- terminal failed-run card contains message, summary, history, and retry button.
- non-failed-run errors render as a simple card.

### Evidence format

- E2E screenshots or snapshots for mobile-width retry waiting, retry calling, expanded history, and exhausted final card.
- API assertions for `/live.run.retry` and terminal `system_error.payload.failure.attempts`.
- WebSocket event capture showing `live_run_updated` on failed attempts.

### CI policy

- Backend model/unit tests and frontend typecheck/lint/story tests run in regular CI.
- Deterministic retry E2E runs in regular E2E CI once fixture support exists.
- Live-provider tests are optional and must not be required for this behavior.

### Fail criteria

- A retry attempt appears as durable transcript history before terminal finalization.
- The terminal failed-run error message is rendered outside the card.
- Retry countdown requires server-side per-second events.
- Manual retry adds a synthetic user message.
- Manual retry leaves the exhausted failed card visible in the latest-following timeline after the retry is accepted.

## Validation Notes

- ADR-0084 already establishes retry as durable run lifecycle state projected to live state.
- ADR-0054 classifies run state and model-call waiting as other live state, not partial history.
- The current backend `/live` response already has `run.retry`, but the frontend discards it.
- The current WebSocket pipeline does not publish structured live run snapshots when retry state changes.
- The existing edit flow already proves that soft-reverting visible history from a model-order boundary is an accepted mechanism for re-entering the loop after an idle control action.

## ADR Need

No new ADR is required if the implementation follows this design. It refines ADR-0084 UX and API recovery behavior without changing the core retry/finalization ownership decision. Update the living specs after implementation.
