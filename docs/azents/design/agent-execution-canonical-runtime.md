---
title: "Agent Execution Canonical Runtime Design"
created: 2026-05-27
updated: 2026-05-28
implemented: 2026-05-28
tags: [architecture, backend, engine, llm]
---

# Agent Execution Canonical Runtime Design

## Status

Implemented. Decisions from ADR-0039 were promoted to canonical runtime production path and Living Spec.

Related documents:

- [ADR-0039: Agent Execution Transcript Normalization](../adr/0039-agent-execution-transcript-normalization.md)
- [Context Compaction Design](./context-compaction.md)
- [OpenAI SDK Migration - Events Unification Redesign](./openai-sdk-events-redesign.md)
- [Builtin/provider tool tracking issue](https://github.com/azents/azents/issues/4100)

## Background

Current azents agent execution is owned by OpenAI Agents SDK based `OpenAIEngineAdapter`. If Agents SDK stream is interrupted midway, UI may have seen partial delta but completed SDK item batch may not reach durable event store.

The larger structural problem is that existing session must continue even when model/provider/client changes. Using SDK raw item or LiteLLM raw response as DB source of truth is convenient while native format is same, but transcript continuity breaks when continuing with different provider/model/client.

Therefore, new runtime aims for following.

- Keep durable source of truth as azents canonical transcript.
- Use adapter raw artifact only as same-native replay optimization.
- Remove both Agents SDK production code and legacy raw LiteLLM runtime code.
- Azents owns model step, tool loop, run state, compaction, and recovery.

## Goals

- Provide session continuity based on canonical transcript.
- Implement first adapter with LiteLLM Responses API.
- Define adapter boundary so future official OpenAI client, Anthropic native client, any-llm can replace it.
- Aim for existing feature parity. Subagent, background tool, compaction, stop/cancel, image/file artifacts, provider tools policy are included in v1 design scope.
- Remove existing SDK/legacy runtime production path into clean state.

## Non-goals

- Do not migrate existing session/event data. Use destructive cutover under private-service premise.
- Durable storage of partial streaming delta is not v1 goal. Durable event is created based on completed output item.
- Stabilizing hosted builtin tool is not blocking scope of this design. Track separately in #4100.
- Do not make provider-specific live spike a prerequisite. Use legacy LiteLLM normalization code and tests as golden behavior reference.

## Top-Level Structure

```text
Worker
  -> AgentRunExecution
       -> load session transcript from model_input_head_event_id
       -> PreLowerFilterPipeline
       -> AdapterLowerer
       -> PostLowerFilterPipeline
       -> ModelAdapter.stream()
       -> AdapterOutputNormalizer
       -> append canonical events
       -> execute client tools
       -> append tool results
       -> repeat until run terminal
```

Important boundary:

```text
canonical transcript -> AdapterLowerer -> adapter native request
adapter native output -> AdapterOutputNormalizer -> canonical transcript
```

`ModelAdapter` does not know canonical. It is transport wrapper that receives adapter native request and emits native stream events. Lowerer and normalizer know canonical.

## Canonical Transcript

Canonical event is split into envelope and payload.

```text
CanonicalEvent
  id: uuid7 hex text
  session_id
  type
  item
  external_id?
  adapter?
  provider?
  model?
  native_format?
  schema_version
  created_at
```

Ordering uses `id` without separate sequence.

```text
ORDER BY id ASC
```

Required invariant:

```text
Same session transcript append happens only under single writer/run lock.
```

### Event Kinds

```text
user_message
assistant_message
reasoning

client_tool_call
client_tool_result
provider_tool_call
provider_tool_result

turn_marker
run_marker

compaction_marker
compaction_summary

subagent_start
subagent_end

system_reminder
system_error

unknown_adapter_output
```

`image_generation_item` is not separate kind. Provider hosted image generation is normalized as `provider_tool_call` / `provider_tool_result`.

### Native Artifact

Native artifact is required only on adapter/model output origin payloads.

```text
NativeArtifact[TNativeItem]
  compat_key: str
  adapter: str
  native_format: str
  provider: str
  model: str
  schema_version: str
  item: TNativeItem
```

`item` is adapter-native opaque payload that canonical layer does not interpret.

Pass-through condition:

```text
event.native_artifact.compat_key == target_lowerer.compat_key
```

If condition matches, lowerer can insert raw artifact into native request as-is. Otherwise, it reconstructs target native shape from canonical fields.

Native artifact required:

```text
assistant_message
reasoning
client_tool_call
provider_tool_call
provider_tool_result
unknown_adapter_output
```

Native artifact absent:

```text
user_message
client_tool_result
turn_marker
run_marker
compaction_marker
compaction_summary
subagent_start
subagent_end
system_reminder
system_error
```

## Payload Shapes

### Messages

```text
user_message
  content: str | InputContentPart[]
  attachments: Attachment[]
  metadata: dict[str, str]
```

Do not put `headers` in canonical payload. Absorb needed values into `metadata`.

```text
assistant_message
  content: str | OutputContentPart[]
  attachments: Attachment[]
  native_artifact: NativeArtifact
```

`assistant_message.content` is output by assistant, so uses `output_*` parts. When lowering to next model input, lowerer converts to `input_*` part for target API.

### Reasoning

```text
reasoning
  text: str | null
  summary: str | null
  native_artifact: NativeArtifact
```

`text` and `summary` are distinguished. Cross-model lowering drops both. Do not convert to assistant, user, or system text.

### Tools

```text
client_tool_call
  call_id: str
  name: str
  arguments: str
  native_artifact: NativeArtifact

provider_tool_call
  call_id: str
  name: str
  arguments: str | null
  native_artifact: NativeArtifact
```

Store `arguments` as original JSON string. Do not parse into object and store in canonical.

```text
ToolOutputPart =
  output_text
  output_image
  output_file
  output_audio
  output_video
```

```text
client_tool_result
  call_id: str
  name: str | null
  status: completed | failed | cancelled | interrupted
  output: ToolOutputPart[]
  attachments: Attachment[]

provider_tool_result
  call_id: str
  name: str | null
  status: completed | failed | cancelled | interrupted
  output: ToolOutputPart[]
  attachments: Attachment[]
  native_artifact: NativeArtifact
```

Tool result output is always part array in canonical. When lowering to LiteLLM/OpenAI Responses, if there is only one text part it can lower to string output.

### Markers

```text
turn_marker
  run_id: str
  usage: TokenUsage | null

run_marker
  run_id: str
  status: completed | stopped | failed | interrupted
  error?: str

compaction_marker
  compaction_id: str
  status: started | failed
  reason?
  error?

compaction_summary
  compaction_id: str
  content: str
  covered_until_event_id?

subagent_start
  subagent_run_id: str
  subagent_id: str
  subagent_name: str
  subagent_session_id: str

subagent_end
  subagent_run_id: str
  subagent_id: str
  subagent_session_id: str
  status: completed | failed | interrupted
  result?
  error?

system_reminder
  text: str

system_error
  content: str
  severity?
  recoverable?
  reset_suggested?
```

## Attachments And Artifacts

`attachments` is not event common field. It exists only on payloads that actually own file/artifact.

```text
attachments available:
  user_message
  assistant_message
  client_tool_result
  provider_tool_result
```

Attachment is Exchange artifact ref.

```text
Attachment
  uri
  name
  media_type
  size_bytes
  thumbnail?
  text_preview?
```

When Attachment enters model input, render as XML manifest inside owning event. Do not split into separate user message.

```xml
<attachments>
  <attachment
    uri="exchange://artifacts/..."
    name="report.pdf"
    media_type="application/pdf"
    size_bytes="184220"
  />
</attachments>
```

Generated image/file is created as Exchange artifact in output normalizer stage.

```text
provider native response
  -> AdapterOutputNormalizer
  -> extract generated bytes/file ref
  -> create Exchange artifact
  -> add to provider_tool_result attachments
  -> event store append
```

Artifact limits:

```text
max_inline_artifact_bytes = 8 MiB
max_event_json_bytes = 16 MiB
max_total_output_bytes_per_event = 24 MiB
```

If primary generated artifact exceeds inline limit and Exchange storage also fails, corresponding tool/provider result is `status=failed`. If assistant text was generated normally and only additional attachment storage failed, store assistant message and append separate `system_error`.

## Model Input Build

```text
canonical DB rows
  -> PreLowerFilterPipeline
       canonical -> canonical
       adapter agnostic
       DB mutation allowed
  -> AdapterLowerer
       canonical -> adapter native request
       adapter specific
       model capability aware
  -> PostLowerFilterPipeline
       adapter native request -> adapter native request
       adapter specific
       no DB mutation
  -> ModelAdapter.stream()
```

Pre-lower filter handles canonical transcript. It allows DB mutation to avoid redoing expensive lifecycle conversion results on every request.

Examples:

- downsize old image or replace with placeholder
- mask old large tool observation
- replace large inline payload with attachment manifest and placeholder

Even if pre-lower filter modifies DB, original Exchange artifact and attachment ref must be preserved.

AdapterLowerer knows native format. First implementation is `LiteLLMResponsesLowerer`.

Post-lower filter is final guard for adapter native request.

- request size guard
- provider-specific native schema cleanup
- remove unsupported native field
- last-mile truncation

## Adapter Protocols

```text
AdapterLowerer[TNativeRequest]
  compat_key: str
  lower(
    events: list[CanonicalEvent],
    tools: list[ToolSpec],
    builtin_tools: list[BuiltinToolSpec],
    model_config: ModelConfig,
  ) -> TNativeRequest

PostLowerFilter[TNativeRequest]
  apply(request: TNativeRequest) -> TNativeRequest

ModelAdapter[TNativeRequest, TNativeStreamEvent]
  stream(request: TNativeRequest) -> AsyncIterator[TNativeStreamEvent]

AdapterOutputNormalizer[TNativeStreamEvent]
  on_stream_event(event: TNativeStreamEvent) -> StreamProjectionEvent | None
  on_completed(event_or_response: object) -> list[CanonicalEvent]
```

Streaming durable policy:

```text
on_stream_event -> UI projection only
on_completed    -> durable canonical events
```

Adapter that has no completed response and only stream item done can assemble completed item inside normalizer internal accumulator.

## Tool Loop

Azents owns tool loop. Adapter performs only one model step.

Rules:

- If model step output contains multiple `client_tool_call`, run foreground tools in parallel.
- Next model step runs only after every foreground `client_tool_result` has been appended.
- Background tool appends initial result first, and actual completion is injected later by durable registry.
- Provider tool is considered already executed by provider; Azents does not rerun it.
- If `client_tool_call` was durably stored but run closes without result, append synthetic `client_tool_result(status=interrupted)`.

Failure policy:

- Agent-facing error is delivered as `client_tool_result(status=failed)` output text.
- Infrastructure/internal error is converted to generic model-facing message.
- Clean cancel is `status=cancelled`.
- If result cannot be known due to worker shutdown/restart, status is `interrupted`.
- Foreground tool with unclear idempotency is not automatically rerun.

## Run Execution State

Do not use SDK `RunState`. Azents-owned `agent_runs` row represents current run state.

```text
AgentRun
  id: uuid7 hex
  run_id: uuid7 hex
  session_id
  status: running | stopping | completed | stopped | failed | interrupted
  phase:
    idle
    preparing_input
    waiting_for_model
    streaming_model
    normalizing_output
    executing_tools
    appending_events
    compacting
    stopping
  phase_started_at
  last_completed_event_id: str | null
  active_model_step_id: str | null
  active_tool_calls: ActiveToolCall[]
  stop_requested: bool
  error: str | null
  created_at
  updated_at
```

```text
ActiveToolCall
  call_id: str
  name: str
  arguments: str
  started_at
  background: bool
```

`phase` is source for UI activity as well as recovery.

- `waiting_for_model` / `streaming_model`: agent running indicator
- `executing_tools`: tool activity UI
- `compacting`: context summarization UI

Apply redaction/summarization to `ActiveToolCall.arguments` before UI publish.

## Compaction

Transcript remains append-only. Compaction does not delete previous events and moves `agent_sessions.model_input_head_event_id` to new `compaction_summary.id`.

```text
AgentSession
  model_input_head_event_id: str | null
```

Model input load:

```text
events where id >= model_input_head_event_id order by id asc
```

Compaction success:

```text
1. append compaction_marker(status=started, compaction_id)
2. select summary target range
3. append compaction_summary(compaction_id, content, covered_until_event_id)
4. model_input_head_event_id = compaction_summary.id
```

Compaction failure:

```text
append compaction_marker(status=failed, compaction_id, error)
head pointer does not move
```

Keep existing policies.

- trigger threshold: `max_input_tokens * 0.9`
- protection: `max_input_tokens * 0.3`
- summary max tokens: `max_input_tokens * 0.1`
- fallback budget: `0.25` of threshold
- protect original observations for latest 2 completed runs
- if tool output `> 2_000` chars, preserve head `1_200` and tail `600` chars
- manual compact is force compact

## Builtin Provider Tools

Provider hosted tool enters request as `BuiltinToolSpec`.

```text
BuiltinToolSpec
  name: str
  config: dict
  required: bool
```

Policy:

```text
supported:
  include in request as native hosted tool

unsupported + required=false:
  omit from request

unsupported + required=true:
  fail with system_error before run starts
```

Client fallback is used only when explicitly configured. Hosted builtin tool support scope and currently broken behavior are tracked separately in #4100.

## DB Design

Cutover uses shadow table method. Final table names stay simple.

```text
events
agent_sessions
agent_runs
```

During migration, temporary suffix is used.

```text
events_next -> events
agent_sessions_next -> agent_sessions
agent_runs_next -> agent_runs
```

Common patterns:

- `sa.String(32)` UUID7 hex primary key
- `TimeZoneDateTime` timestamps
- PostgreSQL `JSONB`
- SQLAlchemy `ENUM(..., create_type=False, values_callable=...)`
- chronological row order is `ORDER BY id ASC`

### events

```text
events
  id: String(32) primary key default uuid7().hex
  session_id: String(32) not null references agent_sessions(id) ondelete cascade
  type: event_type enum not null
  item: JSONB not null
  external_id: Text null
  adapter: Text null
  provider: Text null
  model: Text null
  native_format: Text null
  schema_version: Text not null
  created_at: TimeZoneDateTime server_default now()

indexes:
  ix_events_session_id(session_id)
  ix_events_session_id_id(session_id, id)
  ix_events_session_type_id(session_id, type, id)
  uq_events_session_external(session_id, external_id)
    where external_id is not null
```

### agent_sessions

Keep existing `agent_sessions` columns and add head pointer and schema version.

```text
agent_sessions
  id: String(32) primary key default uuid7().hex
  workspace_id: String(32) not null references workspaces(id) ondelete cascade
  agent_runtime_id: String(32) not null references agent_runtimes(id) ondelete cascade
  agent_id: String(32) not null references agents(id) ondelete cascade
  status: agent_session_status enum not null default active
  start_reason: agent_session_start_reason enum not null default initial
  end_reason: agent_session_end_reason enum null
  model_input_head_event_id: String(32) null
  transcript_schema_version: Text not null
  started_at: TimeZoneDateTime server_default now()
  lifecycle_started_at: TimeZoneDateTime null
  ended_at: TimeZoneDateTime null
  created_at: TimeZoneDateTime server_default now()
  updated_at: TimeZoneDateTime server_default now() onupdate now()
```

### agent_runs

```text
agent_runs
  id: String(32) primary key default uuid7().hex
  run_id: String(32) not null unique
  session_id: String(32) not null references agent_sessions(id) ondelete cascade
  status: run_execution_status enum not null
  phase: run_execution_phase enum not null
  phase_started_at: TimeZoneDateTime not null
  last_completed_event_id: String(32) null
  active_model_step_id: String(32) null
  active_tool_calls: JSONB not null
  stop_requested: Boolean not null default false
  error: Text null
  created_at: TimeZoneDateTime server_default now()
  updated_at: TimeZoneDateTime server_default now() onupdate now()

indexes:
  ix_agent_runs_session_id(session_id)
  ix_agent_runs_session_status(session_id, status)
  ix_agent_runs_updated_at(updated_at)
```

`model_input_head_event_id` must logically be event id of same session. Whether to use physical FK is decided during implementation considering shadow table rename and compaction update order.

## Implementation Plan

### Phase 1: Schema And Canonical Types

- New enums for canonical event type, run status, run phase.
- New canonical Pydantic payload union.
- Shadow tables for `events`, `agent_sessions`, `agent_runs`.
- Repositories for transcript append/list, session head pointer, run state.
- UUID7 monotonic ordering test.

### Phase 2: LiteLLM Responses Adapter

- `LiteLLMResponsesLowerer`
- `LiteLLMResponsesPostLowerFilter`
- `LiteLLMResponsesModelAdapter`
- `LiteLLMResponsesOutputNormalizer`
- Port golden normalization rules from legacy `runtime/llm.py` tests.

### Phase 3: Azents-Owned Loop

- `AgentRunExecution` orchestration.
- Model step loop.
- Parallel foreground tool execution.
- Background tool initial result path.
- Stop/cancel/interrupted semantics.
- `agent_runs.phase` updates for UI activity.

### Phase 4: Filters And Compaction

- Pre-lower image lifecycle filter with DB mutation.
- Pre-lower observation masking filter with DB mutation.
- Compaction summary append and `model_input_head_event_id` movement.
- Post-lower adapter request guard.

### Phase 5: Subagent And External Entrypoints

- Replace subagent SDK path.
- Update command path for manual compact.
- Update worker/service/deps to depend on new engine protocol.
- Preserve current worker public contract where possible.

### Phase 6: Clean Deletion

- Delete `engine/sdk/**`.
- Delete legacy `runtime/llm.py` after moving any still-needed rendering helper.
- Remove production `agents` dependency.
- Remove SDK-only tests and replace with canonical runtime tests.
- Shadow table cutover, old table drop/archive, rename new tables.

## Feasibility Check

### What Looks Feasible

SDK dependency is concentrated enough to replace through adapter boundary.

Observed production imports point mainly to:

- `azents.engine.run.deps.get_agent_engine`
- `azents.worker.worker`
- `azents.worker.deps`
- `azents.services.agent_runtime`
- `azents.engine.run.commands`
- `azents.engine.tools.subagent`

The broadest dependency surface is `engine/sdk/**`, but callers outside that package mostly depend on `OpenAIEngineAdapter` public behavior rather than Agents SDK internals. This supports protocol replacement approach.

Legacy LiteLLM normalization already exists in `runtime/llm.py` and tests. It is not new implementation base, but sufficient as golden behavior reference for:

- text deltas
- function argument deltas
- reasoning deltas
- completed response usage
- tool call id normalization
- malformed tool argument behavior
- Responses API request kwargs

Existing RDB patterns match new schema plan:

- UUID7 hex `String(32)` ids
- `JSONB` payloads
- `TimeZoneDateTime`
- `ENUM(... create_type=False)`
- `session_id,id` ordering indexes

Compaction policy is well defined in current code and can be preserved while changing storage semantics from delete-and-insert to append-and-head-pointer.

### Main Risks

Tool loop replacement is largest behavioral risk. SDK currently owns turn sequencing, max turns, tool execution cadence, and some stream item finalization. New loop must explicitly test parallel tool calls, missing result repair, stop/cancel, and max turn termination.

Run resume semantics are not simple SDK `RunState` port. New design intentionally does not replay SDK internal state. Recovery is checkpoint based. This is simpler and more controllable, but behavior after model-stream interruption changes: no assistant item is durable unless completed output exists.

Subagent path still imports SDK engine/session directly. It needs first-class path through new engine protocol, not thin import swap.

Compaction head pointer changes data semantics. UI can still show full history, but model input starts from `model_input_head_event_id`. Repositories and readers must make distinction explicit.

Attachment/artifact handling has DB row size risk. Chosen v1 limits allow larger rows; acceptable for private rollout but needs monitoring.

Builtin provider tools are intentionally not blocking this redesign. Required/optional policy is clear, but actual provider support remains tracked in #4100.

### Feasibility Verdict

Feasible, but not as rollback. This is clean replacement.

Previous raw LiteLLM code reduces normalizer risk but does not provide full runtime loop, run state, compaction head pointer, or subagent replacement. Right implementation strategy is stacked replacement:

```text
schema/types -> adapter -> run loop -> filters/compaction -> subagent/worker cutover -> cleanup
```

Do not try to delete SDK and legacy LiteLLM first. Build new canonical runtime behind new protocol, switch callers, then delete old code.

## Test Strategy

### Unit Tests

- Canonical payload validation per event kind.
- Native artifact required/absent invariant.
- UUID7 ordering invariant for same-process generation.
- Compat key pass-through and fallback lowering.
- LiteLLM Responses lowerer for messages, tools, attachments, reasoning drop.
- LiteLLM Responses normalizer for text, reasoning, tool calls/results, provider generated artifacts.
- Tool loop parallel execution and result pairing.
- Synthetic interrupted result when call has no result.
- Run phase transitions and active tool call arguments redaction.
- Pre-lower image lifecycle and observation masking idempotency.
- Compaction head pointer movement and failure no-op behavior.

### Integration Tests

- Worker run with text-only model response.
- Worker run with one client tool.
- Worker run with parallel client tools.
- Stop during model stream.
- Stop during tool execution.
- Worker stale recovery closes active foreground tools as interrupted.
- Manual compact appends summary and moves `model_input_head_event_id`.
- Session history API can still render events before head pointer.

### E2E Primary Matrix

| Behavior | E2E check |
|---|---|
| Text run completes | chat stream emits content and run complete |
| Tool run completes | UI receives tool call/result and final assistant text |
| LLM activity indicator | run phase becomes `waiting_for_model`/`streaming_model` during inference |
| Tool activity indicator | run phase becomes `executing_tools` with active tool call name/arguments |
| Manual compact | compaction marker/summary visible, later LLM input starts from summary |
| Stop | run marker status is `stopped`, UI leaves running state |
| Worker interruption recovery | stale run becomes `interrupted`, missing tool results repaired |

E2E is primary for user-visible behavior. Testenv/live provider tests are optional diagnostics. Live LLM tests must be skipped when credentials are missing and must not assert semantic quality of model text.

### Fixture And Evidence Requirements

- Sanitized native adapter fixtures may be committed when needed.
- Raw provider traces with credentials, headers, or user content must not be committed.
- Golden fixtures should focus on minimal native payloads that exercise normalizer branches.
- CI should run unit and integration tests without live provider credentials.
- Optional live tests may run manually or in credentialed nightly job.

## QA Checklist

### Canonical Transcript Source Of Truth

- What to check: Verify every durable model/tool/session output is stored after passing canonical event kind and payload invariant.
- Why it matters: If canonical transcript is not source of truth, session continuity is again tied to raw adapter artifact on provider/model switch.
- How to check: canonical payload validation unit tests, repository append/read tests, and inspect stored event kind/payload in text/tool integration run.
- Expected result: user, assistant, reasoning, client/provider tool, marker, compaction, subagent, system event are stored as canonical schema and native artifact required/absent invariant is not broken.
- Execution result: PASS. Canonical payload/repository/runtime tests are covered by `cd python/apps/azents && uv run pytest src/azents/runtime -q` (654 passed).
- Fixes applied: Phase 10 preserved legacy user input context while converting it to canonical `user_message` payloads.

### LiteLLM Responses Adapter

- What to check: Verify canonical transcript lowers to LiteLLM Responses native request and Responses stream output is normalized into canonical events and UI projection.
- Why it matters: First production adapter must replace legacy raw LiteLLM behavior to allow SDK removal.
- How to check: run lowerer/normalizer golden unit tests, same-native compat key pass-through tests, text/tool/reasoning/generated artifact normalization tests.
- Expected result: same-native artifact pass-through when compat key matches; cross-model lowering does not convert reasoning text/summary into content; generated image/file output is normalized into provider tool result and attachments.
- Execution result: PASS. LiteLLM Responses lowerer/normalizer tests are covered by `cd python/apps/azents && uv run pytest src/azents/runtime/canonical -q`.
- Fixes applied: Phase 10 routes OpenAI deterministic tests through `AZ_OPENAI_BASE_URL` so canonical production switching keeps the test model adapter path.

### Azents-Owned ReAct Loop

- What to check: Verify model step, tool execution, event append, repeat loop, terminal run marker work without SDK Runner.
- Why it matters: Core of this redesign is removing Agents SDK production path and making azents own execution loop.
- How to check: run text-only run, single tool run, parallel tool run, max-turn interruption, stop/cancel unit/integration tests.
- Expected result: model output is appended as canonical events, foreground tools execute in parallel, execution continues to next model turn after tool results, and terminal status is accurately recorded.
- Execution result: PASS. Runtime integration tests are covered by `cd python/apps/azents && uv run pytest src/azents/runtime -q`; #4112 deterministic E2E is running as PR-level product check.
- Fixes applied: Phase 10 fixed model input preservation after production canonical engine switch.

### Run State And UI Activity

- What to check: Verify `agent_runs` phase and `active_tool_calls` are sufficient as UI activity source.
- Why it matters: After SDK `RunState` removal, stale recovery, LLM running indicator, and tool activity UI depend on new durable state.
- How to check: phase transition tests, stop during stream/tool tests, stale recovery tests, and verify phase projection in WebSocket/UI E2E.
- Expected result: LLM indicator is shown by `waiting_for_model`/`streaming_model`; tool activity by `executing_tools` and redacted/summarized active tool calls.
- Execution result: PASS for runtime-level phase tests via `cd python/apps/azents && uv run pytest src/azents/runtime -q`; PR CI covers deterministic E2E projection.
- Fixes applied: No verification-phase code fix beyond Phase 10 model context/base URL fix.

### Append-Only Compaction

- What to check: Verify compaction does not delete old events, appends marker/summary, and moves `model_input_head_event_id` to summary event.
- Why it matters: Design decision is to preserve UI/audit history while reducing only model input window.
- How to check: compaction repository/unit tests, manual compact integration test, session history API regression test.
- Expected result: old events remain, summary event is appended, and later model input starts from summary head.
- Execution result: PASS. Compaction tests are covered by `cd python/apps/azents && uv run pytest src/azents/engine/context/compaction_test.py -q`.
- Fixes applied: Phase 11 moved compaction summary behavior out of deleted SDK package and kept LiteLLM Responses summary call in `engine/context/compaction.py`.

### Subagent And External Entrypoints

- What to check: Verify worker, service, command, subagent entrypoints execute through canonical engine protocol, not SDK concrete adapter.
- Why it matters: Batch invoke, worker run, slash command, and subagent behavior must remain after SDK path removal.
- How to check: run worker/service/subagent integration tests and grep to confirm SDK-only imports remain absent from production path.
- Expected result: production entrypoints depend on canonical engine implementation, and subagent start/end events are stored as canonical events.
- Execution result: PASS. Subagent and external runtime tests are covered by `cd python/apps/azents && uv run pytest src/azents/engine/tools/subagent_test.py -q` and `cd testenv/azents && uv run pytest testenv/tests -q` (131 passed).
- Fixes applied: No verification-phase code fix required.

### Cleanup And Cutover

- What to check: Verify OpenAI Agents SDK production path, legacy raw `runtime/llm.py` production path, SDK `RunState`, old shadow-table names are removed in final cleanup.
- Why it matters: Goal is clean replacement, not retaining compatibility layer.
- How to check: perform dependency graph/grep check, pyright/ruff, full azents tests, migration downgrade/upgrade review, final PR cleanup diff review.
- Expected result: final production path is canonical runtime, and old SDK/legacy code disappears from production imports except test fixtures or document references.
- Execution result: PASS for code cleanup. `openai-agents`, `azents.engine.sdk`, `azents.runtime.llm`, and legacy `LLMClient` reference scans return no matches in production code after Phase 11.
- Fixes applied: Phase 11 removed `engine/sdk/**`, `runtime/llm.py`, SDK-only tests, and the `openai-agents` dependency.

## Open Follow-Ups

- Decide exact module layout during implementation.
- Decide whether `model_input_head_event_id` gets a physical FK.
- Define redaction policy for active tool call arguments.
- Track hosted builtin tool support in #4100.
