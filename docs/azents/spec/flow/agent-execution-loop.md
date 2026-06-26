---
title: "Agent Execution Loop"
created: 2026-04-20
tags: [backend, engine]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation, toolkit]
code_paths:
  - python/apps/azents/src/azents/engine/run/contracts.py
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
  - python/apps/azents/src/azents/services/agent_runtime/**
  - python/apps/azents/src/azents/services/input_buffer.py
  - python/apps/azents/src/azents/services/model_file.py
  - python/apps/azents/src/azents/services/file_lifecycle.py
  - python/apps/azents/src/azents/repos/input_buffer/**
  - python/apps/azents/src/azents/repos/model_file/**
  - python/apps/azents/src/azents/services/model_listing/**
  - python/apps/azents/src/azents/rdb/models/event.py
  - python/apps/azents/src/azents/rdb/models/agent_session.py
  - python/apps/azents/src/azents/rdb/models/agent_run.py
  - python/apps/azents/src/azents/rdb/models/model_file.py
  - python/apps/azents/src/azents/rdb/models/workspace_model_settings.py
  - python/apps/azents/src/azents/worker/worker.py
  - python/apps/azents/src/azents/worker/session/**
last_verified_at: 2026-06-26
spec_version: 45
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

1. Worker promotes input buffers to event `RunUserMessage` input.
2. `AgentEngineAdapter` appends event `user_message` to the durable transcript while deduping by `RunUserMessage.external_id`.
3. `AgentRunExecution` repeats model steps and tool steps while updating `agent_runs.phase`.
4. `PreLowerFilterPipeline` normalizes event transcript content for model input and may mutate event payloads for request-independent transcript repair, but it does not own attachment/file lifecycle cleanup.
5. `LiteLLMResponsesLowerer` lowers event transcript, client tools, hosted tools, and model kwargs
   into a LiteLLM Responses native request.
6. `PostLowerFilterPipeline` applies adapter-native request size guard.
7. `LiteLLMResponsesModelAdapter.stream()` calls the raw LiteLLM Responses API.
8. `AdapterOutputNormalizer` normalizes native output into events and UI stream projection.
9. Foreground client tools execute in parallel and results are appended as event `client_tool_result`.
10. When no foreground client tool call or pending follow-up remains, the runner observes the
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
- `subagent_start`
- `subagent_end`
- `system_reminder`
- `goal_continuation`
- `goal_updated`
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

The pre-lower order is significant. Event attachment/file lifecycle filters run before automatic
compaction. The runtime does not omit old tool outputs in normal model input. If the lowered request
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
`user`, even though they are not user-authored chat messages. The lowerer renders all
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

## 5. Tool Loop

`AgentRunExecution` executes foreground client tool calls in parallel. Each tool result is normalized
to a `client_tool_result` with status:

- `completed`
- `failed`
- `cancelled`
- `interrupted`

Foreground tool execution must be bounded. Runtime-backed tools such as `read`, `write`, `grep`,
`glob`, `stat`, and `bash` dispatch Runner operations with an explicit non-null deadline and pass
that deadline through the reply-stream wait path. If the Runner request or reply is dropped, the
operation times out into a failed/cancelled tool result path instead of leaving a durable
`client_tool_call` without a corresponding `client_tool_result` forever.

Tool result output is `str | content part list`. Text-only tools may return a string. Multipart
output uses semantic event parts: `text`, `attachment`, `artifact`, and `file`, with legacy
`output_image`/`output_file`/audio/video parts accepted only through compatibility paths. Consumers
iterate output through event helper APIs instead of assuming a single shape.

Tool result output stored in event history remains the durable source of truth. Client tool result
text has a global hard cap of 30,000 characters at the event tool execution boundary, regardless of
which toolkit produced the result. For text over the cap, the runtime stores a truncation marker and
the tail of the output. This cap applies after builtin, external, subagent, and custom toolkit handlers
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
not by URI. ModelFile blobs are request-local inputs during lowering only. ADR-0046 lifecycle transitions are scheduler-owned: image blobs degrade at run age 1 and 3, image ModelFiles become unreachable at run age 10, and non-image ModelFiles become unreachable at run age 3. The scheduler later marks unreachable ModelFiles deleted after one run-boundary grace and retries blob deletion until `blob_deleted_at` is recorded. Normal chat run input preparation does not synchronously expire Exchange files, Artifacts, or ModelFiles. No durable event, REST/WS projection, or frontend state stores raw bytes, inline base64, data URL, or provider-native file payload.

Before the event engine builds the tool catalog, `AgentWorker` resolves the
desired toolkit list for the message and `_SessionRunner` reconciles it through the
session-scoped toolkit lifecycle registry. The returned `RunRequest.toolkits` snapshot
contains entered toolkit instances only. The engine then calls
`update_context(TurnContext)` on that snapshot to build current tool specs and prompt
fragments.

`TurnContext` carries current run values such as `run_id`, `publish_event`, current
actor `user_id`, model, and optional stop checker. Session-scoped toolkit instances
must create run-sensitive handlers from this current turn context instead of retaining
stale constructor state. Schedule and subagent tool handlers follow this rule.

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
- sequential appends leave gaps in model order to allow later summary/tail reordering without
  renumbering the whole transcript.

Automatic compaction summarizes only the older compacted portion and preserves recent tail turns as
raw events. After the summary is appended, the summary receives an intermediate model order
between the compacted range and the preserved tail. The next model step therefore naturally sees
`compaction_summary` followed by the raw tail without a special branch in the input builder. The
preserved tail keeps its existing model order when a gap is available.

Successful automatic compaction writes `auto_threshold_exceeded` to both the marker and summary
payload reason. Explicit `/compact` writes `manual_command` to both payloads.

Manual compaction and fallback compaction continue to compact the full selected slice and do not
preserve a separate raw tail. Compaction summary generation uses LiteLLM Responses API directly from
`engine/context/compaction.py`. If summary generation fails, the failure is propagated to the caller instead
of being published as a successful compaction. The existing transcript remains append-only.

## 7. Entrypoints And Projection

Production dependency injection returns `AgentEngineAdapter`. Worker, service, and subagent
entrypoints depend on `AgentEngineProtocol`, not SDK concrete adapters.

Web chat user writes enter through REST commit endpoints. Message writes create or reuse an
`AgentSession`, materialize user input attachments, record the accepted write under
`client_request_id`, commit an input buffer, then send a broker wake-up signal. Edit writes are
idle-only: the REST transaction rewrites durable history state, clears pending input buffers,
creates an `edited_user_message` input buffer, marks the session running, and sends a wake-up.
Command writes are idle-only control actions: the REST transaction stores one pending command on
`agent_sessions`, marks the session running, and sends a wake-up. Running sessions, existing pending
commands, or pending input buffers reject command/edit writes with `409 Conflict`. Stop uses the REST
control endpoint `POST /chat/v1/sessions/{session_id}/stop`; it records a durable DB stop intent and
sends a best-effort broker stop signal for immediate cancellation. WebSocket message/edit/command/stop
payloads and the old `/chat/v1/sessions/new` WebSocket first-message route are no longer
execution-loop entrypoints. WebSocket is a server-to-client projection transport only.

Public web chat projection is split by lifecycle:

- durable transcript reads use `GET /chat/v1/sessions/{session_id}/history`;
- current streaming/tool/pending-input state uses `GET /chat/v1/sessions/{session_id}/live`;
- WebSocket transport publishes `history_event_appended`, `live_event_upserted`, and
  `live_event_removed` actions.

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
- `cd testenv/azents/e2e && uv run pyright src/tests/azents/public/test_chat_input_buffer.py`
- REST chat write targeted verification: `cd python/apps/azents && uv run pytest -q src/azents/api/public/chat/v1/chat_api_test.py src/azents/repos/chat_write_request/repository_test.py src/azents/services/chat/input_buffer_test.py`
- REST chat write and preemptive stop E2E/browser blocker tracking: GitHub issues #4468 and #4469
- static scan for removed `openai-agents`, `azents.engine.sdk`, `azents.runtime.llm`, and
  legacy `LLMClient` references


## Idle continuation

Idle transition is allowed only at a terminal run boundary. `AgentSession.run_state` may become `idle` only
after the runner has observed a terminal `RunComplete` boundary and has confirmed that there is no
follow-up work: no pending command, no pending input buffer, and no queued actionable wake-up. User
interrupt and unrecoverable turn errors also end through `RunComplete`; after that same follow-up
check they may transition the session to idle.

Wake-up is a signal, not work by itself. If a wake-up reaches a running session, it is a no-op signal.
If a wake-up reaches the runner and there is no pending command, input buffer, or other actionable
work, the runner must no-op instead of forcing a model call.

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
