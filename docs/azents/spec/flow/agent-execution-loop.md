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
  - python/apps/azents/src/azents/core/inference_profile.py
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
  - typescript/apps/azents-web/src/features/chat/components/ChatView.tsx
  - typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts
last_verified_at: 2026-07-14
spec_version: 79
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

1. Worker reads exactly one FIFO InputBuffer head, resolves the requested profile when that input requires inference, and then locks the same head for atomic preparation.
2. Preparation atomically updates the Session inference snapshot, applies Goal/Skill side effects, appends canonical events, associates run input, and deletes the source buffer. A changed FIFO head restarts preparation instead of applying a stale resolution.
3. Worker executes buffer-keyed operation TurnActions such as `create_git_worktree` before the next model dispatch. The current Session owner generation admits the execution before buffer deletion; active state and progress remain in execution tables until one atomic terminal handover appends durable history and deletes live state.
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
and the admitting `owner_generation`. PostgreSQL is the execution and live-state authority for this set. The UI LLM running indicator is derived only from the active Run phase: it appears in `waiting_for_model`, remains visible for the entire `streaming_model` phase even after partial model output becomes visible, and disappears when the phase advances beyond `streaming_model`. Tool activity uses `executing_tools` and `active_tool_calls`.

`action_executions` and `action_execution_events` are likewise live execution state, not a second
terminal history store. Each active operation stores its admitting Session `owner_generation` and
remains `pending` or `running` in those tables. Completed, failed, and cancelled shapes exist only in
the final durable snapshot. A terminal transaction locks the live row, appends the deterministic
`action_execution_result:{execution_id}` event, and deletes the execution with its progress rows.

A newly selected run begins as `pending`. For normal buffered input, the worker resolves the
Agent-owned target label and optional effort before transactionally preparing the FIFO head. Successful
preparation stores the complete Session inference snapshot and uses it to activate or continue the
run. A canonical human `user_message` stores the immutable requested target label and raw nullable
requested effort accepted with that input. It does not copy the resolved physical selection or the
applied model display name from the prepared Session snapshot. Exact applied public provenance belongs
to the `turn_marker` for each provider call, so requested intent remains stable after reload while
applied provenance can differ at later turn boundaries. Resolution failure is a handled preparation
failure: it consumes that head, appends a user-safe `system_error`, preserves the previous Session
snapshot, completes the active run, and is not retried.

Requested profile selection precedence for implicit execution is the Session current requested
profile then Agent `main_model_label`; explicit human input wins over both. The complete Session
snapshot contains requested label, resolved physical selection, resolved effort, effective limits,
and resolution time. Inputs accepted during a model/tool turn are applied only at the next turn
boundary. If that input changes the profile, the same `AgentRun` rebuilds the next model request from
the newly prepared Session snapshot. It does not restore an older run-owned model selection or cancel
the run merely to change profiles. Commands use the implicit selection but have no client-submitted
profile.

Model-call preparation carries that exact turn-local Session snapshot through `RunRequest` and
`PreparedModelCall`. When provider usage is appended, the `turn_marker` copies the snapshot's public
applied profile and effective limits. A multi-turn run can therefore contain different immutable
marker snapshots after a boundary profile change; it never stamps all turns with one run-start
selection or queries a later Session value while appending an earlier turn.

`terminal_result_event_id` and `terminal_result_message` store the user-safe terminal output projection for a completed, failed, stopped, interrupted, or cancelled run. Subagent parent observation and Subagent Tree unread/result previews read this projection instead of scanning child transcript history.

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

When retry wait expires and the next attempt starts, `RunExecutor` clears `agent_runs.retry_state`
and publishes a `live_run_updated` snapshot with `run.retry = null` so stale retry UI disappears
while normal model/tool progress continues. The in-memory executor still carries the previous
attempt summaries for the next failure in the same run. Known non-retryable failures, such as
deterministic fixture strict-mode `no_fixture_match`, are classified with `retryability =
non_retryable`, receive `backoff_seconds = 0`, and are finalized on the first failed attempt instead
of waiting for the retry budget. When retry is
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

`AgentWorker` resolves the requested main target before the engine starts. The target label is resolved only against the current Agent-owned selectable option snapshots; Workspace defaults and model catalogs are not consulted. The selected main snapshot, requested effort, effective context limit, and compaction threshold become immutable `AgentRun` provenance. The Agent's lightweight snapshot remains the compaction model. The execution core receives physical selections and limits in `RunRequest`, never the target label.

`LiteLLMResponsesLowerer` owns the full provider-native request surface for the Responses adapter:
transport credential kwargs, generation kwargs, client function tool passthrough, and provider-hosted
tool lowering. Agent `model_parameters.builtin_tools` stores semantic ids such as `web_search`; the
lowerer maps them to provider/model-developer native shapes and fails before provider call if the
selected model capability does not support the requested hosted tool.

Both `xai` and `xai_oauth` use the xAI transport target in this lowerer. For either identity, system instructions become the first `system` input item instead of top-level `instructions`, hosted `web_search` uses the xAI Responses tool target, and Anthropic cache-control hints are omitted. Credential refresh is resolved before the adapter pipeline and remains exclusive to `xai_oauth`; the lowerer does not own OAuth lifecycle state.

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
following normal user message for the request. The source Skill `action_message` InputBuffer is consumed without creating a duplicate transcript
event.

## 4.1 Subagent Scheduling and Mailbox Input

Subagent runs use the same worker, broker, `AgentSession`, and `AgentRunExecution` path as root runs.
Before resolving tools, the worker reads the selected session. If `agent_sessions.session_kind = subagent`,
toolkit resolution uses subagent execution mode; otherwise it uses root execution mode. Subagent mode
excludes root/user-facing auto-bound capabilities such as Memory Write and Goal Toolkit
while keeping the subagent collaboration toolkit available.

Subagent collaboration tools communicate through resolved agent input buffers:

- `spawn_agent` first enforces the Agent's active subagent and depth limits while holding a root
  `SessionAgent` row lock for the tree. It fails with a tool error instead of queueing when the root
  tree already has `subagent_settings.max_subagents` active subagents or the requested child would
  exceed `subagent_settings.max_depth`. If allowed, it creates
  a child `SessionAgent` plus hidden child `AgentSession`. Without a profile override it precreates the child's first pending run with source `parent_run` and the exact current parent-run requested and resolved profile, limits, and parent run id. For `fork_turns = none` or a positive bounded count, optional `model_target_label` and `reasoning_effort` fields may instead pre-resolve an Agent-owned target profile with source `spawn_override`. Full-history `all` forks reject either override. Target-only changes normalize effort from the parent resolved effort; explicit efforts validate exactly. Label, effort, fork, and parent-provenance validation happens before child records or wake-up side effects. The tool description lists Agent-owned labels and explicit effort levels only and does not project physical model or integration metadata. The spawn flow then forks the parent's selected model-visible
  context, appends that selected context to the child transcript, appends a
  `system_reminder` event rendered as a `<system-reminder>` boundary when any parent history
  was copied, writes an initial `agent_message`, marks the child running, and sends a broker
  wake-up. The caller may still
  explicitly select no context or a bounded number of recent turns through `fork_turns`. The
  boundary reminder is inserted immediately after copied parent history for `fork_turns=all` or a
  positive integer selection. It identifies the child by name and full path, marks preceding messages
  as inherited parent context, and states that `wait_agent` only observes descendants rather than the
  current agent. `wait_agent` also rejects an explicitly resolved self target at tool execution time.
- Agent references follow Codex v2 visibility and targeting semantics within the current root tree.
  `list_agents` includes the root and the known agent tree, including ancestors of the caller.
- `send_message` writes an `agent_message` to any resolved agent, including the root, without waking it.
- `followup_task` writes an `agent_message`, marks the target running, and sends a broker wake-up,
  but rejects the root as a target.
- `interrupt_agent` rejects the root and the caller itself, then records stop intent only for the
  resolved target's current run.

`agent_message` lowering renders the mailbox payload as an explicit task envelope for the target
child session. `spawn_agent` and `followup_task` render `Message Type: NEW_TASK`; `send_message`
renders `Message Type: MESSAGE`. The envelope includes the target path as task name, sender path,
and payload text so a subagent can distinguish its current assignment from inherited forked
history. The first child run initializes `agent_sessions.last_model_target_label` and
`last_reasoning_effort` from its selected requested profile. Later `followup_task` runs therefore use
normal session-last-used precedence and re-resolve the saved Agent-owned label against the current
Agent snapshot rather than pinning the first run's physical snapshot. Broker wake-ups remain
payload-free; recovery is based on persisted input buffers and `agent_sessions.run_state`.

Human-authored direct writes are root-session only. REST message/edit/command/failed-run retry paths reject `session_kind = subagent` before creating input buffers,
chat write requests, pending commands, operation mutations, live projections, or broker wake-ups.
Subagent mailbox input must be written by another SessionAgent through collaboration tools as
`agent_message` buffers.

User-facing stop is subtree-aware: stopping a root session records stop intent for running linked
descendants, and stopping a child detail session records stop intent for that child subtree.
Model-visible `interrupt_agent` is intentionally narrower and records stop intent only for the named
target agent's current run after rejecting the root and the caller itself.

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

If the run is stopped while tools are active, the loop records deterministic cancelled results for calls that
did not produce a result. User-requested stop also appends an `interrupted` durable event before the
terminal `run_marker(status=interrupted)` so the next model input can receive the interruption
reminder and the UI can show a non-chat timeline divider. After user stop, the session runner starts
another turn only when pending input buffers remain. If no pending input buffer exists, queued wake-up
messages for the same session are discarded so reconnect or duplicate wake-up signals do not resume
model execution by themselves.

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
worktree. Those actions are FIFO `action_message` InputBuffers, not transcript events or
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
Operation TurnActions are processed after input-buffer preparation and before model dispatch at both
wake-up entry and model-call turn boundaries inside an already-running run. `create_git_worktree`
action execution is keyed by the source `input_buffer_id`; the preparation transaction stores the
typed action payload, current Session owner generation, and pending execution before deleting the
source buffer. Before invoking a side effect, the worker verifies that generation and admits the
operation through the same shutdown barrier used by foreground tools. Execution publishes live
projection updates while status or log entries change, creates the worktree through typed Runner Git
operations, registers the created path as a session Project, refreshes catalog/Skill projection, and
then invalidates the prepared context boundary.

This same path covers new-session setup actions and existing-session Register Project worktree
actions. After successful Project mutation, the same active `AgentRun` rebuilds model/tool context
and the next physical model request from the current Session inference snapshot. If an action fails,
it is terminal and FIFO processing may continue to later pending input without a retry/discard
mutation. Completion, failure, and cancellation all use one transaction that copies the current
execution and ordered progress events into one `action_execution_result`, then deletes the live row.
The stable execution ID joins live and durable projections.

At every new Session processing boundary, the current owner terminalizes any leftover operation as
cancelled before admitting new work. It never resumes or re-executes an uncertain stale side effect.
Worker shutdown closes new operation admission and allows the supervised foreground task up to 30
seconds to finish. Timeout cancels the task and persists a cancelled snapshot before ownership is
released. User stop cancels immediately through the existing foreground-task path; the operation
records a user-stop cancellation snapshot while the Run follows normal preemptive stop semantics.

Stop uses the REST control endpoint `POST /chat/v1/sessions/{session_id}/stop`; it records a durable
DB stop intent and sends a best-effort broker stop signal for immediate cancellation. WebSocket
message/edit/command/stop
payloads and the old `/chat/v1/sessions/new` WebSocket first-message route are no longer
execution-loop entrypoints. WebSocket is a server-to-client projection transport only.

Public web chat projection is split by lifecycle:

- durable transcript reads use `GET /chat/v1/sessions/{session_id}/history`;
- current streaming/tool/pending-input state uses `GET /chat/v1/sessions/{session_id}/live`;
- WebSocket transport publishes canonical action envelopes such as `history_event_appended`,
  `live_event_upserted`, `live_event_removed`, `action_execution_updated`, and
  `action_execution_removed`.

A durable `Event` is nested inside `history_event_appended`; it is never sent as a raw top-level public
WebSocket frame. REST writes commit their authoritative database state before projection. When the
committed state requires worker execution, the route sends the essential broker wake-up before any
best-effort WebSocket notification. A broker wake-up failure remains an execution-path failure, while
a WebSocket publication failure is logged and does not change the success of the committed REST
write or delete.

`WorkerEventPublisher.dispatch_event()` preserves the durable/live handoff order. For `Event`, the
publisher broadcasts the durable history action and then removes and broadcasts matching live
projections. Explicitly public controls (`runtime_error`, authorization and account-link controls,
compaction controls, `todo_state_changed`, and `subagent_tree_changed`) retain their direct wire
frames. Internal provider deltas and Run/runtime lifecycle telemetry update the live projector without
being broadcast directly; the projector emits canonical live actions where applicable. Live-store
mutation, active-tool projection, live Run publication, and WebSocket broadcast are non-authoritative
UI projection boundaries: they preserve `asyncio.CancelledError`, log other projection failures, and
do not fail provider execution, durable event append, Run phase/terminal persistence, or subsequent
cleanup.

`ContentDelta` and `ReasoningDelta` are live projection events only. The worker applies every delta to
the Redis live projection and emits `live_event_upserted` immediately. There is no time- or
character-based partial batching layer. Engine emit ordering therefore keeps each live update ahead
of a later durable assistant/reasoning event, whose history action is published before the matching
live projection is removed.

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
- deterministic action-based Git worktree lifecycle E2E coverage, including existing-session Register Project actions, durable buffer-keyed execution recovery, and terminal success/failure history
- `cd testenv/azents/e2e && uv run pyright src/tests/azents/public/test_chat_input_buffer.py`
- Failed-run retry recovery E2E: `cd testenv/azents/e2e && uv run pytest src/tests/azents/public/test_agent_execution_persistence.py -q -k failed_run`
- Per-prompt target, effort, provenance, and resolution-failure E2E: `cd testenv/azents/e2e && uv run pytest src/tests/azents/public/test_per_prompt_inference_profile.py -q`
- REST chat write targeted verification: `cd python/apps/azents && uv run pytest -q src/azents/api/public/chat/v1/chat_api_test.py src/azents/repos/chat_write_request/repository_test.py src/azents/services/chat/input_buffer_test.py`
- REST chat write and preemptive stop E2E/browser blocker tracking: GitHub issues #4468 and #4469
- static scan for removed `openai-agents`, `azents.engine.sdk`, `azents.runtime.llm`, and
  legacy `LLMClient` references


## Changelog

- **2026-07-12** — v73. Added exact terminal Run correlation, durable-before-publication ordering, and exact per-turn inference provenance.
- **2026-07-12** — v71. Promoted sequential single-head preparation, Session-owned per-turn inference snapshots, buffer-only action transport, buffer-keyed operation execution, handled preparation failures, and same-run profile changes.
- **2026-07-11** — v70. Added bounded-fork subagent inference overrides, label-only schema guidance, atomic validation, and session-last-used continuation semantics.
- **2026-07-10** — v69. Added profile-aware FIFO promotion, atomic run activation, immutable resolved provenance, and exact parent-run profile inheritance.
- **2026-07-10** — v68. Documented shared xAI API-key/OAuth transport lowering while preserving OAuth-only credential refresh.
- **2026-07-09** — v66. Documented forked-history `<system-reminder>` boundaries, explicit agent-message envelopes, and Codex v2 agent targeting and list visibility.
- **2026-07-09** — v65. Clarified that selectable model labels are resolved before run start and runtime receives effective model snapshots only.
- **2026-07-09** — v64. Documented `spawn_agent` active subagent and depth limit enforcement before child-session side effects.
- **2026-07-09** — v63. Documented default subagent context forking and child-session human write rejection before side effects.
- **2026-07-08** — v62. Documented subagent worker scheduling through normal session runs, `agent_message` mailbox promotion, subagent execution-mode tool resolution, terminal result projections, and subtree stop behavior.
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

Terminal control events identify one concrete run. `RunComplete`, `RunStopped`, and live-run clear
payloads require `run_id`; consumers apply them only when that ID exactly matches the run being
completed or cleared. The worker persists the terminal AgentRun status and result projection before
publishing the matching terminal control event. A delayed Run A event cannot terminate or clear a
newer Run B. Generic SessionRunner error reporting does not synthesize `RunComplete`: failures that
escape an active Run use durable failed-run finalization, while failures before Run activation remain
error observations without a terminal Run event.

The required run-completion order is:

1. Persist the terminal AgentRun state and durable terminal transcript output.
2. Publish or observe the correlated terminal control event (`RunComplete` or `RunStopped`).
3. Check whether follow-up work already exists.
4. If follow-up work exists, keep or restore `running` and continue with the next run.
5. If no follow-up work exists, transition `AgentSession.run_state` to `idle`.
6. Clear session activity state that belongs to the completed run.
7. Run `on_session_idle` hooks.
8. Collect returned continuation prompts.
9. Enqueue collected prompts through `InputBufferService`, which inserts the buffers and marks
   `AgentSession.run_state` as `running` in the same database transaction.
10. Publish pending-buffer live state and send a broker wake-up signal.

`on_session_idle` hook providers do not write durable transcript events directly and do not send
broker wake-ups. They return continuation input only. The input-buffer service owns the atomic
handoff from idle hook result to recoverable runner work.

A graceful worker shutdown is not an idle transition. If shutdown is observed while a run is active,
the departing worker preserves `running` state and hands over by wake-up instead of marking the
session idle or dispatching idle hooks. The supervised foreground task receives a bounded 30-second
completion window. Tool-call recovery may continue from its durable ownership protocol, but an
uncertain operation TurnAction is cancelled into durable history and is never resumed by the next
owner.

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

- **2026-07-14** (spec_version 79) — Defined operation TurnActions as owner-generation-fenced live execution state with atomic terminal snapshot/delete handover, 30-second shutdown completion, preemptive user-stop cancellation, and no stale-owner re-execution.
- **2026-07-13** (spec_version 78) — Reverted incremental native-stream normalization from version 77 and removed time- and character-based live partial batching so every existing content and reasoning delta updates Redis and WebSocket projection immediately.
- **2026-07-13** (spec_version 77) — Made native model stream normalization incremental so text and reasoning projections are emitted before provider completion without retaining the full native event sequence.
- **2026-07-13** (spec_version 76) — Clarified that the LLM running indicator remains visible through the complete model streaming phase, including after partial output appears.
- **2026-07-13** (spec_version 75) — Promoted immutable requested input intent, non-fatal live projection boundaries, essential wake-up ordering, and explicit public WebSocket delivery boundaries.
- **2026-07-12** (spec_version 74) — Added atomic tool-call admission/completion, deterministic cancellation and result identity, ownership-generation recovery, and PostgreSQL-backed active-call state.
- **2026-07-12** (spec_version 72) — Restored durable sent-message model label, resolved display name, and reasoning effort metadata from the prepared Session snapshot.
- **2026-07-10** (spec_version 67) — Added explicit child identity to forked-history boundaries and rejected self-targeted `wait_agent` calls.
- **2026-07-09** (spec_version 65) — Clarified that retry live state is cleared before the next retry attempt starts so stale retry errors do not remain visible during successful progress.
- **2026-07-06** (spec_version 58) — Promoted existing-session Register Project worktree actions and action retry/discard mutation semantics.
- **2026-07-05** (spec_version 57) — Added operation TurnAction execution projection updates during status/log changes.
- **2026-07-04** (spec_version 54) — Clarified that the session runner drains pending initialization work before dispatch and may continue into run creation on the same wake-up once setup becomes ready.
- **2026-07-04** (spec_version 52) — Added the session initialization gate before run creation.
- **2026-07-01** (spec_version 50) — Unified pending runtime commands into the `RunExecutor` run boundary.
- **2026-07-05** (spec_version 56) — Promoted failed-run retry recovery state, attempt history, live-run WebSocket projection, terminal error-card metadata, and manual retry control behavior.
- **2026-06-28** (spec_version 47) — Added failed-run retry state foundation, live retry projection contract, and Goal continuation gating by successful terminal run status.
- **2026-06-28** (spec_version 46) — Promoted generic client tool result metadata and runtime process tool execution (`exec_command`/`write_stdin`) into the execution loop spec.
