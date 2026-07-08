---
title: "Agent Execution Loop"
created: 2026-04-20
tags: [backend, engine]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation, toolkit]
code_paths:
  - python/apps/azents/src/azents/engine/run/contracts.py
  - python/apps/azents/src/azents/engine/run/errors.py
  - python/apps/azents/src/azents/engine/io/user_input.py
  - python/apps/azents/src/azents/engine/events/**
  - python/apps/azents/src/azents/engine/tools/**
  - python/apps/azents/src/azents/engine/context/compaction.py
  - python/apps/azents/src/azents/engine/context/window.py
  - python/apps/azents/src/azents/engine/events/**
  - python/apps/azents/src/azents/engine/hooks/**
  - python/apps/azents/src/azents/engine/run/deps.py
  - python/apps/azents/src/azents/api/public/chat/v1/**
  - python/apps/azents/src/azents/core/config.py
  - python/apps/azents/src/azents/services/agent_session_input.py
  - python/apps/azents/src/azents/services/session_git_worktree/**
  - python/apps/azents/src/azents/services/action_execution.py
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents/src/azents/services/input_buffer.py
  - python/apps/azents/src/azents/services/model_file.py
  - python/apps/azents/src/azents/repos/input_buffer/**
  - python/apps/azents/src/azents/repos/action_execution/**
  - python/apps/azents/src/azents/repos/model_file/**
  - python/apps/azents/src/azents/services/model_listing/**
  - python/apps/azents/src/azents/rdb/models/event.py
  - python/apps/azents/src/azents/rdb/models/action_execution.py
  - python/apps/azents/src/azents/rdb/models/agent_session.py
  - python/apps/azents/src/azents/rdb/models/agent_run.py
  - python/apps/azents/src/azents/rdb/models/model_file.py
  - python/apps/azents/src/azents/rdb/models/workspace_model_settings.py
  - python/apps/azents/src/azents/worker/worker.py
  - python/apps/azents/src/azents/worker/run/**
  - python/apps/azents/src/azents/worker/session/**
last_verified_at: 2026-07-08
spec_version: 61
---

# Agent Execution Loop

This is the current execution loop specification in which the agent repeatedly receives user input,
invokes the model, executes tools, stores events, and publishes UI updates. The production path is
not the OpenAI Agents SDK Runner or legacy `runtime/llm.py`, but the azents-owned event runtime.

## 1. Overview

The durable source of truth for one run is the event transcript and `agent_runs` state.
The final `events` table is the event transcript schema. Compatibility emits may remain at existing
worker/UI stream boundaries, but the DB source of truth is the event transcript and `agent_runs`.

Main steps:

1. Worker promotes input buffers to durable event input, including ordered `action_message` events, at wake-up entry and at each model-call turn boundary.
2. Worker executes operation TurnActions such as `create_git_worktree` before the next model dispatch; a failed operation is marked failed and FIFO processing continues to later pending input.
3. `AgentEngineAdapter` appends event `user_message` to the durable transcript while deduping by `RunUserMessage.external_id`.
4. `AgentRunExecution` repeats model steps and tool steps while updating `agent_runs.phase`.
5. `PreLowerFilterPipeline` cleans up event transcript into DB-mutating event transcript.
6. `LiteLLMResponsesLowerer` lowers event transcript, client tools, hosted tools, and model kwargs
   into a LiteLLM Responses native request.
7. `PostLowerFilterPipeline` applies adapter-native request size guard.
8. `LiteLLMResponsesModelAdapter.stream()` calls the raw LiteLLM Responses API.
9. `AdapterOutputNormalizer` normalizes native output into events and UI stream projection.
10. Foreground client tools execute in parallel and results are appended as event `client_tool_result`.
11. When no foreground client tool call or pending follow-up remains, the runner observes the
    terminal `RunComplete` boundary and then transitions `AgentSession.run_state` to idle.

Streaming deltas are UI projection only. Durable events are appended based on completed output items
or completed responses.

## 2. Run State

`agent_runs` replaces SDK `RunState`. Run phase is also the UI activity source.

Phase enum:

- `idle`
- `preparing_input`
- `waiting_for_model`
- `streaming_model`
- `normalizing_output`
- `executing_tools`
- `appending_events`
- `compacting`
- `stopping`

`active_tool_calls` contains `call_id`, `name`, redacted/summarized `arguments`, `started_at`,
and `background`. The UI LLM running indicator uses `waiting_for_model` / `streaming_model`, and
tool activity uses `executing_tools` and `active_tool_calls`.

`retry_state` is nullable durable JSON on `agent_runs`. When present, it records failed-run retry
progress for a still-running run and includes the latest user-safe error message, failed attempt
count, max retries, backoff seconds, `next_retry_at`, error type/source, retryability, failure code,
and a bounded `attempts` list. Each attempt summary contains attempt number, user-safe message,
error type/source, failed timestamp, retryability, failure code, truncation flag, backoff seconds,
and the next retry timestamp. Terminal run transitions clear `retry_state`. `/live` exposes this as
the optional `run.retry` projection so retry UI can restore the live retry card and attempt history
without durable transcript retry-attempt events.

Failed-run retry is owned by the worker run boundary, not by the event execution core. User-visible
model/runtime errors that stop a run attempt propagate out of `AgentRunExecution` without appending a
durable `system_error`, without appending a failed `run_marker`, and without marking the run
terminal. `RunExecutor` converts the propagated failure into `FailedRunAttempt`, persists
`agent_runs.retry_state`, waits until `next_retry_at` while observing stop/shutdown, and retries the
same `run_id`. This keeps the run `running` and prevents durable failed history until retry is
finalized.

When the next attempt succeeds, the normal terminal completed path closes the same `agent_runs` row
and clears `retry_state`. Known non-retryable failures, such as deterministic fixture strict-mode
`no_fixture_match`, are classified with `retryability = non_retryable`, receive `backoff_seconds = 0`,
and are finalized on the first failed attempt instead of waiting for the retry budget. When retry is
exhausted, when a non-retryable failure is observed, or when stop is requested while retry is waiting,
`FailedRunErrorFinalizer` promotes the latest attempt to durable failed-run output by delegating
durable append and terminal run updates to the engine failed-run event store. That event-store
boundary appends the terminal `system_error` with failed-run metadata, appends the failed run marker,
and marks the run `failed` while clearing retry state. The worker finalizer then emits `RunComplete`
and clears live activity.

Command wake-ups execute through the same `RunExecutor` boundary as normal model runs. A pending
command is resolved before the `agent_runs` row is created; unknown-command or pre-run resolve
failures remain direct message-processing failures. Once a command run exists, command failures use
the same failed-run retry/finalizer boundary as normal runs. `SessionRunner` top-level
message-processing errors also remain outside the failed-run scope unless they are already inside the
concrete `RunExecutor` boundary.

Failed-run terminal `system_error` events carry a user-safe `failure` payload with `kind =
failed_run`. The payload includes finalization reason, failed attempt count, retry budget, latest
retryability/failure code, optional `action_hint`, and the same bounded user-safe attempt history
shape used by `run.retry.attempts`. Frontend history/live mapping must preserve this metadata on the
rendered error message. The terminal failed-run error card shows the safe error message inside the
card, exposes the attempt history as expandable detail, and shows a manual retry action only when the
failed-run error event is the latest visible durable event and the session is idle. It must not render
internal messages, stack traces, raw provider responses, or any observability-only diagnostics.

## 3. Event Transcript

Durable event kinds:

- `user_message`
- `background_completion`
- `assistant_message`
- `reasoning`
- `client_tool_call`
- `client_tool_result`
- `provider_tool_call`
- `provider_tool_result`
- `turn_marker`
- `run_marker`
- `interrupted`
- `compaction_marker`
- `compaction_summary`
- `system_reminder`
- `goal_continuation`
- `goal_updated`
- `action_message`
- `skill_loaded`
- `goal_briefing`
- `system_error`
- `unknown_adapter_output`

Native/raw artifacts are not interpreted by event core. They are opaque same-native replay
optimizations. The LiteLLM Responses lowerer replays a native artifact item as-is by default when
this compat key matches. Canonical fallback lowering is used when the compat key does not match.

```text
adapter:native_format:provider:model:schema_version
```

Cross-model lowering drops reasoning text and summary. Reasoning is preserved as event
`reasoning` for UI/audit and is not converted into assistant/user/system content.

## 4. Model Adapter Pipeline

The model pipeline is deliberately adapter-specific and does not use a generic model request IR.

```text
event transcript
  -> PreLowerFilterPipeline
  -> LiteLLMResponsesLowerer
  -> NativeRequestSizeGuard
  -> LiteLLMResponsesModelAdapter.stream()
  -> LiteLLMResponsesOutputNormalizer
  -> events + stream projection
```

Pre-lower filters may mutate DB-backed event transcript state or shape an in-memory transcript
clone for the next model call. Post-lower filters operate on adapter-native request payloads and must
not mutate DB state.

The pre-lower order is significant. Event attachment/file availability filters run before automatic
compaction. Scheduler-owned file cleanup does not run in run input preparation. The runtime does not omit old tool outputs in normal model input. If the lowered request
is still too large, `NativeRequestSizeGuard` remains the final post-lower hard guard.

`LiteLLMResponsesLowerer` owns the full provider-native request surface for the Responses adapter:
transport credential kwargs, generation kwargs, client function tool passthrough, and provider-hosted
tool lowering. Agent `model_parameters.builtin_tools` stores semantic ids such as `web_search`; the
lowerer maps them to provider/model-developer native shapes and fails before provider call if the
selected model capability does not support the requested hosted tool.

Generated image/file output and provider-hosted tool output from the model are normalized as
provider tool call/result events with attachments or text payloads. These provider tool events do not
enter the client tool execution loop and do not by themselves continue the model turn.

Synthetic model-visible reminders are durable events or control events whose model lowering role is
`user`, even though they are not user-authored chat messages. The lowerer renders most
reminder-like inputs through the same XML envelope:

```xml
<system_reminder type="...">
  <instruction>
    ...
  </instruction>
  <data>
    <item name="...">
      ...
    </item>
  </data>
</system_reminder>
```

Current reminder types are:

- `goal_continuation`
- `goal_updated`
- `compaction_summary`
- `system_reminder`
- `interrupted`

The durable payload stores only normalized state, snapshots, or summary content. Prompt prose is
materialized at lower time by the lowerer and is included in token estimation through the same
renderer. The XML structure is fixed across reminder types: event-specific values such as
`goal_objective`, `summary`, or `reason` are represented only as `<item name="...">` entries under
`<data>`. Reminder types without event-specific data render an empty `<data />` element. UI must not
render these reminders as user-authored bubbles.

`skill_loaded` is the exception to the shared XML reminder envelope. A Skill turn action promotes a
`skill_loaded` event followed by a normal `user_message` event when the action message is non-empty.
The `skill_loaded` payload stores the exact Skill path, full body, content hash, source hints, and the
original user action message. The Responses lowerer injects it as a user-role instruction that says
the Skill has been loaded, requires the model to read and follow the embedded body, and points to the
following normal user message for the request. The durable Skill `action_message` is audit data and is
not actionable model input.

## 5. Tool Loop

`AgentRunExecution` executes foreground client tool calls in parallel. Each tool result is normalized
to a `client_tool_result` with status:

- `completed`
- `failed`
- `cancelled`
- `interrupted`

Foreground tool execution must be bounded. Runtime-backed tools such as `read`, `write`, `grep`,
`glob`, `stat`, `exec_command`, and `write_stdin` dispatch Runner operations with an explicit
non-null deadline and pass that deadline through the reply-stream wait path. If the Runner request or reply is dropped, the
operation times out into a failed/cancelled tool result path instead of leaving a durable
`client_tool_call` without a corresponding `client_tool_result` forever.

Tool result output is `str | content part list`, and client tool results may also carry a generic JSON-object `metadata` payload. The engine preserves metadata on `client_tool_result` events without branching on toolkit-specific keys. Runtime process tools use metadata for process status/session id/exit code/truncation/missing facts, while model-visible output remains normal tool-result text. Text-only tools may return a string. Multipart
output uses semantic event parts: `text`, `attachment`, `artifact`, and `file`, with legacy
`output_image`/`output_file`/audio/video parts accepted only through compatibility paths. Consumers
iterate output through event helper APIs instead of assuming a single shape.

Tool result output stored in event history remains the durable source of truth. Client tool result
text has a global hard cap of 30,000 characters at the event tool execution boundary, regardless of
which toolkit produced the result. For text over the cap, the runtime stores a truncation marker and
the tail of the output. This cap applies after builtin, external, and custom toolkit handlers
return, so individual tool implementations do not own separate general-purpose output truncation.
Normal model input lowering keeps old tool output content instead of replacing it with
context-pressure placeholders.

`attachment` parts represent user-agent delivery files and lower to bounded metadata text only.
`artifact` parts represent agent/tool internal file output and lower to bounded metadata text with
`artifact://...` URI. `file` parts represent ModelFile-backed rich model input. FilePart native
lowering is resolved model capability driven; unsupported or missing request-local content becomes
a bounded placeholder and is not silently omitted.

Attachment and Artifact parts are not automatically converted into FilePart. Explicit FilePart
creation stores a normalized ModelFile and durable events reference it by `model_file_id`,
not by URI. A `model_file_id` is single-event scoped; later reuse of the same source bytes materializes
a new ModelFile/FilePart. ModelFile blobs are request-local inputs during lowering only and are protected
by active run pins while the run depends on them. Persistent ModelFile run-age degradation/unreachable
stages are not part of the execution loop; scheduler-owned GC deletes unpinned ModelFiles after their
single FilePart event falls behind the model-input head cursor. No durable event, REST/WS projection,
or frontend state stores raw bytes, inline base64, data URL, or provider-native file payload.

Before the event engine builds the tool catalog, `AgentWorker` resolves the
desired toolkit list for the message and `_SessionRunner` reconciles it through the
session-scoped toolkit lifecycle registry. The returned `RunRequest.toolkits` snapshot
contains entered toolkit instances only. The engine then calls
`update_context(TurnContext)` on that snapshot to build current tool specs and prompt
fragments.

`TurnContext` carries current run values such as `run_id`, `publish_event`, current
actor `user_id`, model, and optional stop checker. Session-scoped toolkit instances
must create run-sensitive handlers from this current turn context instead of retaining
stale constructor state. Schedule and background task tool handlers follow this rule.

If the run is stopped while tools are active, the loop records interrupted results for calls that
did not produce a result. User-requested stop also appends an `interrupted` durable event before the
terminal `run_marker(status=interrupted)` so the next model input can receive the interruption
reminder and the UI can show a non-chat timeline divider. After user stop, the session runner starts
another turn only when pending input buffers remain. If no pending input buffer exists, queued wake-up
messages for the same session are discarded so reconnect or duplicate wake-up signals do not resume
model execution by themselves. Background tools return an initial result path without blocking the
foreground model loop.

## 6. Compaction

Compaction is append-only:

- old events are not deleted;
- `compaction_marker` and `compaction_summary` are appended with the same `compaction_id` and trigger reason;
- `agent_sessions.model_input_head_event_id` moves to the compaction summary event id;
- model input reads events by model order, so physical append order is not the model-visible
  ordering contract;
- sequential appends leave gaps in model order so later model-visible system events can be inserted
  without renumbering the whole transcript.

Automatic compaction summarizes the full selected model-input transcript, then runs the
`on_compaction_summary` hook pipeline against the generated summary before appending continuity. The
compaction summary payload then embeds bounded `Recent User Messages` and `Recent Transcript`
sections. The user-message section contains the last five user messages independent of turn
boundaries; the transcript section contains readable model-visible excerpts from the last five
completed model turns of the same compacted transcript. The next model step therefore sees a single
`compaction_summary` head event that contains the durable checkpoint, any hook enrichment, and recent
continuity context.

Successful automatic compaction writes `auto_threshold_exceeded` to both the marker and summary
payload reason. Explicit `/compact` writes `manual_command` to both payloads.

Manual compaction uses the same summary-plus-continuity structure as automatic compaction. The
runtime no longer keeps a separate raw tail by moving the compaction boundary; recent continuity is
embedded into the summary payload with per-event truncation. Compaction summary generation uses
LiteLLM Responses API directly from `engine/context/compaction.py`. If summary generation fails, the
failure is propagated to the caller instead of being published as a successful compaction. The
existing transcript remains append-only.

## 7. Entrypoints And Projection

Production dependency injection returns `AgentEngineAdapter`. Worker and service
entrypoints depend on `AgentEngineProtocol`, not SDK concrete adapters.

Web chat user writes enter through REST commit endpoints. Message writes create or reuse an
`AgentSession`, materialize user input attachments, record the accepted write under
`client_request_id`, commit an input buffer, then send a broker wake-up signal. New-session writes may
also enqueue ordered setup action inputs, such as `create_git_worktree`, before the first user message
so operation setup runs before the first model run. Existing-session writes may also enqueue ordered
operation action inputs for user-requested workspace mutations, such as Register Project → New
worktree. Those action inputs are durable `action_message` events in the turn order, not
session-initialization setup rows. Edit writes are
idle-only: the REST transaction rewrites durable history state, clears pending input buffers,
creates an `edited_user_message` input buffer, marks the session running, and sends a wake-up.
Command writes are idle-only control actions: the REST transaction stores one pending command on
`agent_sessions`, marks the session running, and sends a wake-up. Manual failed-run retry uses
`POST /chat/v1/sessions/{session_id}/retry-failed-run` with `agent_id`, `failed_event_id`, and
`client_request_id`. It is accepted only when the target event is a visible failed-run
`system_error`, the session is idle with no pending command or input buffer, and that event is the
latest visible durable event. The accepted write type is `failed_run_retry`; it soft-reverts visible
events from the failed event model-order boundary, clears pending buffers defensively, marks the
session running, sends a normal wake-up, and requires history reload. It does not append a synthetic
user message. `SessionRunner` reads the pending
command from the session and passes it into `RunExecutor`, which prepares the same `RunRequest` and
`RunContext` used by normal runs before invoking the registered command handler. Running sessions,
existing pending commands, or pending input buffers reject command/edit writes with `409 Conflict`.
Operation TurnActions are processed after input-buffer promotion and before model dispatch at both
wake-up entry and model-call turn boundaries inside an already-running run. `create_git_worktree`
action execution is keyed by its durable `action_message` event, records durable progress in
`action_executions`, publishes action execution projection updates while status or log entries
change, creates the worktree through typed Runner Git operations, registers the created path as a
session Project, refreshes catalog/Skill projection, and then invalidates the prepared context
boundary. This same operation-action path covers new-session setup actions and existing-session
Register Project worktree actions. If later pending input remains after a Project-mutating action
succeeds at a turn boundary, the runner marks the current agent run cancelled without appending a
completed run marker, sends a follow-up wake-up, and stops the current processing boundary so the next
pass rebuilds model/tool context from the updated Project registry. If an action fails at a turn
boundary, the action execution is marked failed and FIFO processing continues to later pending input
without waiting for retry/discard. Retry and discard mutations remain scoped to failed operation
action executions, return the updated action execution projection, and enqueue a normal broker
wake-up when more runner work is needed. Terminal completed worktree actions also append an
`action_execution_result` durable event containing the final action execution projection, then live
state excludes terminal action executions so completed logs survive history reload without persisting
as live-only fallback.

Stop uses the REST control endpoint `POST /chat/v1/sessions/{session_id}/stop`; it records a durable
DB stop intent and sends a best-effort broker stop signal for immediate cancellation. WebSocket
message/edit/command/stop
payloads and the old `/chat/v1/sessions/new` WebSocket first-message route are no longer
execution-loop entrypoints. WebSocket is a server-to-client projection transport only.

Public web chat projection is split by lifecycle:

- durable transcript reads use `GET /chat/v1/sessions/{session_id}/history`;
- current streaming/tool/pending-input state uses `GET /chat/v1/sessions/{session_id}/live`;
- WebSocket transport publishes `history_event_appended`, `live_event_upserted`,
  `live_event_removed`, and `action_execution_updated` actions.

`WorkerEventPublisher.dispatch_event()` preserves the durable/live handoff order. For `Event`, the
publisher broadcasts the durable history action first, then removes and broadcasts matching live
projections. Non-event runtime events keep the live projection update → broadcast ordering.

`ContentDelta` and `ReasoningDelta` are live projection events only. The worker batches them in a
session-local `LivePartialBatcher` before Redis live store upsert and `live_event_upserted` broadcast.
Pending batches flush before event durable event handling and before terminal `RunComplete` /
`RunStopped` handling, so finalized durable assistant/reasoning events do not overtake buffered live
text.

The old `GET /chat/v1/sessions/{session_id}/messages` aggregate endpoint is removed. The POST
`/chat/v1/sessions/{session_id}/messages` write endpoint is a separate REST commit boundary and does
not restore the removed aggregate reader. Frontend chat state does not depend on legacy
`content_delta`, `reasoning_delta`, `function_call_delta`, `run_started`, `run_phase_changed`,
`input_buffered`, or `input_buffer_deleted` events.

Worker-internal stream projections may still exist as adapter output normalization helpers, but public
chat state is restored from durable history, live projections, and event WebSocket actions. Event
transcript plus `agent_runs` remain the execution state source of truth.

Adapter output normalization does not import `runtime/llm.py`.

## 8. Verification

Primary checks:

- `cd python/apps/azents && uv run pytest src/azents/runtime/file_resource_lifecycle_verification_test.py -q`
- `cd python/apps/azents && uv run pytest src/azents/runtime -q`
- `cd python/apps/azents && uv run pytest src/azents/engine/events/execution_test.py src/azents/engine/events/filters_test.py src/azents/engine/events/engine_adapter_test.py`
- `cd python/apps/azents && uv run pyright`
- deterministic azents E2E CI for text/tool/UI projection behavior
- deterministic action-based Git worktree lifecycle E2E coverage, including existing-session Register Project worktree actions and action retry/discard recovery
- `cd testenv/azents/e2e && uv run pyright src/tests/azents/public/test_chat_input_buffer.py`
- Failed-run retry recovery E2E: `cd testenv/azents/e2e && uv run pytest src/tests/azents/public/test_agent_execution_persistence.py -q -k failed_run`
- REST chat write targeted verification: `cd python/apps/azents && uv run pytest -q src/azents/api/public/chat/v1/chat_api_test.py src/azents/repos/chat_write_request/repository_test.py src/azents/services/chat/input_buffer_test.py`
- REST chat write and preemptive stop E2E/browser blocker tracking: GitHub issues #4468 and #4469
- static scan for removed `openai-agents`, `azents.engine.sdk`, `azents.runtime.llm`, and
  legacy `LLMClient` references


## Changelog

- **2026-07-08** — v61. Process TurnActions at every model-call turn boundary; failed actions are marked failed and FIFO processing continues, while context invalidation exits through a follow-up wake-up without a completed run marker.
- **2026-07-08** — v60. Process TurnActions at every model-call turn boundary and close the current run when an operation action blocks or invalidates context.
- **2026-07-06** — v59. Removed the session-initialization run gate and documented terminal `action_execution_result` history events.
- **2026-07-05** — v56. Reflected operation TurnAction processing before model dispatch and Project context invalidation after worktree setup.

## Idle continuation

Idle transition is allowed only at a terminal run boundary. `AgentSession.run_state` may become `idle` only
after the runner has observed a terminal `RunComplete` boundary and has confirmed that there is no
follow-up work: no pending command, no pending input buffer, and no queued actionable wake-up. User
interrupt and failed terminal runs also end through `RunComplete`; after that same follow-up check
they may transition the session to idle. Idle continuation hooks are dispatched only when the latest
terminal run status is `completed`; failed, stopped, interrupted, cancelled, or retry-active running
runs must not enqueue Goal continuation.

Wake-up is a signal, not work by itself. If a wake-up reaches a running session, it is a no-op signal.
The warm runner polls input buffers at model-call turn boundaries, so accepted TurnActions are not
held until the run-complete boundary. If a wake-up reaches the runner and there is no pending command,
input buffer, or other actionable work, the runner must no-op instead of forcing a model call.

The required run-completion order is:

1. Append or observe the terminal run event (`RunComplete`).
2. Check whether follow-up work already exists.
3. If follow-up work exists, keep or restore `running` and continue with the next run.
4. If no follow-up work exists, transition `AgentSession.run_state` to `idle`.
5. Clear session activity state that belongs to the completed run.
6. Run `on_session_idle` hooks.
7. Collect returned continuation prompts.
8. Enqueue collected prompts through `InputBufferService`, which inserts the buffers and marks
   `AgentSession.run_state` as `running` in the same database transaction.
9. Publish pending-buffer live state and send a broker wake-up signal.

`on_session_idle` hook providers do not write durable transcript events directly and do not send
broker wake-ups. They return continuation input only. The input-buffer service owns the atomic
handoff from idle hook result to recoverable runner work.

A graceful worker shutdown is not an idle transition. If shutdown is observed while a run is active,
the departing worker preserves `running` state and hands over by wake-up instead of marking the
session idle or dispatching idle hooks. Stale recovery can then resume from durable state without
waiting for an idle-only path.

The first idle hook provider is Goal Toolkit. It emits continuation only for `active` Goal state.
`paused`, `blocked`, `complete`, or empty Goal state does not enqueue a continuation and does not
wake a run. A `goal_continuation` input buffer promotes to a durable `goal_continuation` event during
the next buffer flush. That event uses a user-message compatible payload with empty attachments and
metadata containing the event-time Goal snapshot (`goal_objective`, `goal_status`, `goal_created_at`,
`goal_updated_at`) plus control fields such as `source=goal` and `provider_slug=goal`. It does not
store the rendered continuation prompt. `LiteLLMResponsesLowerer` renders the model-visible
continuation prompt at LLM input lowering time from the metadata snapshot. UI consumers must not show
a pending user bubble or delete control for this internal control event; they may render a
non-interactive continuation indicator.

When the user updates the session Goal through the public Goal mutation API, the service appends a
durable `goal_updated` control event with the updated Goal snapshot and wakes the session in the same
way. `goal_updated` lowers to a user-role compatible prompt that tells the model the active Goal was
updated by the user.

## Changelog

- **2026-07-06** (spec_version 58) — Promoted existing-session Register Project worktree actions and action retry/discard mutation semantics.
- **2026-07-05** (spec_version 57) — Added operation TurnAction execution projection updates during status/log changes.
- **2026-07-04** (spec_version 54) — Clarified that the session runner drains pending initialization work before dispatch and may continue into run creation on the same wake-up once setup becomes ready.
- **2026-07-04** (spec_version 52) — Added the session initialization gate before run creation.
- **2026-07-01** (spec_version 50) — Unified pending runtime commands into the `RunExecutor` run boundary.
- **2026-07-05** (spec_version 56) — Promoted failed-run retry recovery state, attempt history, live-run WebSocket projection, terminal error-card metadata, and manual retry control behavior.
- **2026-06-28** (spec_version 47) — Added failed-run retry state foundation, live retry projection contract, and Goal continuation gating by successful terminal run status.
- **2026-06-28** (spec_version 46) — Promoted generic client tool result metadata and runtime process tool execution (`exec_command`/`write_stdin`) into the execution loop spec.
