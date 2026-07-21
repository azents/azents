---
title: "Agent Execution Transcript Normalization"
created: 2026-05-27
tags: [architecture, backend, engine, llm, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: execution-260527
historical_reconstruction: true
migration_source: "docs/azents/adr/0039-agent-execution-transcript-normalization.md"
---

# execution-260527/ADR: Agent Execution Transcript Normalization

## Status

Draft. Records decisions confirmed in the 2026-05-27 design discussion.

## Topic

This ADR is not about Agent Runtime.

Agent Runtime defined in [sandbox-260525/ADR](./sandbox-260525-sandbox-redesign.md) is the execution environment that provides code execution and file operations. This ADR covers boundaries for transcript, model adapter, tool loop, and event normalization of agent execution loop running on top of it.

Scope:

- what canonical shape to store conversation/session transcript in
- how to continue existing session after model/provider/client changes
- how to lower canonical transcript into target model native input
- how to normalize adapter native output into canonical transcript
- how to design clean-state execution loop after removing SDK Runner and legacy raw LiteLLM loop

## Background

Existing azents agent execution uses OpenAI Agents SDK based `OpenAIEngineAdapter`. In production, `httpx.RemoteProtocolError: peer closed connection without sending complete message body (incomplete chunked read)` occurred during SDK stream. UI saw streaming delta, but completed SDK item batch never reached `NointernSession.add_items()`, so partial text did not remain in durable transcript.

However, durable partial text storage is excluded from core decisions of this ADR. It is deferred to later streaming draft design.

More important requirement from design discussion is event normalization. Existing session must continue across different model/provider even if user changes model. To achieve that, provider-native raw transcript must no longer be DB source of truth. Instead, introduce azents-owned canonical transcript and native lowering boundary.

## Decisions

### 1. Canonical transcript is durable source of truth

Durable transcript source of truth is azents canonical transcript, not provider-native raw item.

Raw/native artifact may be preserved, but canonical field is primary contract. Raw artifact pass-through is allowed only when continuing with same client/provider/model/native format. If target changes, target native input is rebuilt from canonical transcript instead of inserting raw artifact directly.

```text
canonical transcript row
  canonical fields  # durable truth
  native artifact   # same-native replay optimization
```

Raw artifact pass-through must satisfy at least:

```text
adapter match
native_format match
provider match
model match
schema_version match
```

If client changes from LiteLLM to official OpenAI client, raw artifact is not passed through even if provider/model are same.

`compat_key` is stored inside `native_artifact`.

```text
NativeArtifact
  compat_key: str
  adapter: str
  native_format: str
  provider: str
  model: str
  schema_version: str
  item: TNativeItem
```

Calculation:

```text
compat_key = "{adapter}:{native_format}:{provider}:{model}:{schema_version}"
```

Pass-through condition:

```text
event.native_artifact.compat_key == target_lowerer.compat_key
```

`item` is adapter-native opaque payload not interpreted by canonical contract. Type and shape differ by adapter.

Examples:

```text
LiteLLM Responses adapter
  item: dict[str, Any]

OpenAI official Responses adapter
  item: Response output item dump

Anthropic Messages adapter
  item: content block / tool_use block / tool_result block
```

If condition matches, lowerer of same adapter family may insert raw item directly into target native input. Otherwise lower from canonical payload to target native format.

`native_artifact` exists only on adapter/model output origin payload. If present, it is required, not optional. User/client/runtime-origin events do not have the field.

```text
native_artifact required:
  assistant_message
  reasoning
  client_tool_call
  provider_tool_call
  provider_tool_result
  unknown_adapter_output

native_artifact absent:
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

`client_tool_call` is tool request that azents executes, but request itself is model output, so it has native artifact. `client_tool_result` is result created by azents, so it has no native artifact.

Transcript order has no separate `sequence`; event `id` decides order. `id` uses UUID7 and read order is `ORDER BY id ASC`.

Required invariant:

```text
Append to same session transcript only under single writer/run lock.
```

Checkpoint also references event id, not sequence.

```text
RunExecutionState
  last_completed_event_id
```

UUID7 generator must guarantee monotonic order for ids generated in same millisecond within same process. Final implementation verifies this invariant with tests.

### 2. Adapter boundary is bidirectional

Two explicit boundaries are needed between canonical transcript and adapter native format.

```text
adapter native output -> ModelOutputNormalizer -> canonical transcript
canonical transcript -> TranscriptLowerer -> adapter native input
```

First implementation targets LiteLLM Responses API.

```text
LiteLLMResponsesOutputNormalizer
LiteLLMResponsesLowerer
```

Canonical schema is not tied to LiteLLM. Later switch to official OpenAI client, Anthropic native client, any-llm, etc. should require replacing only lowerer/normalizer implementations.

### 3. SDK Runner is not final loop owner

Azents owns agent execution loop.

Model adapter performs only one model step. SDK Runner or LiteLLM client does not own multi-turn tool loop.

```text
AgentRunExecution
  -> build native input from canonical transcript
  -> model adapter single step
  -> output normalizer emits canonical assistant/tool events
  -> execute client tools
  -> append canonical tool results
  -> next model step
```

As consequence, SDK `Runner.run_streamed()` is removal target in final structure.

### 4. Target clean-state replacement

Final state removes both legacy raw LiteLLM code and Agents SDK production code.

Removal targets:

- `engine/sdk/**`
- legacy raw `runtime/llm.py`
- production `agents` dependency
- SDK-only event formatter/classifier/converter path
- SDK `RunState` storage dependency

Existing code is used only as research/golden behavior reference, not implementation foundation for new runtime.

Because service is still private and no user data migration is required, existing session compatibility migration is not performed. At cutover, existing active sessions/history can be reset, truncated, or discarded by destructive migration.

### 5. Reasoning is dropped in cross-model lowering

Reasoning items can be stored in durable transcript. UI display policy can be separate.

However, cross-model or cross-provider lowering does not pass reasoning. `reasoning_summary_text` is not converted to assistant text, user note, or system note.

Reasons:

- If reasoning summary is inserted as assistant content, target model can misinterpret it as previous assistant output format.
- Even as system/user note, it can pollute next response style.
- Semantics of reasoning/thinking artifacts differ by provider.
- Information needed for session continuity must be in final assistant text, tool call/result, user input, and attachments.

Raw reasoning artifact pass-through may be allowed only for same-native replay.

### 6. Canonical user_message payload

`user_message` is canonical payload of user input.

```text
user_message
  content: str | InputContentPart[]
  attachments: Attachment[]
  metadata: dict[str, str]
```

`role` is not stored redundantly because kind is already `user_message`.

Existing `UserInputEvent.images` is not kept as separate top-level field. Inline media actually sent to model is content part. File references needed for UI/download/session file list are `attachments`. If same file must be both model input and user-visible, put both `content part` and `attachment`.

Existing `headers` are not included in canonical payload. Needed values are absorbed into `metadata` because HTTP/header shape is transport-specific.

```text
InputContentPart =
  input_text
  input_image
  input_file
  input_audio
  input_video
```

### 7. Canonical assistant_message payload

`assistant_message` is assistant response payload generated by model/adapter.

```text
assistant_message
  content: str | OutputContentPart[]
  attachments: Attachment[]
  native_artifact: NativeArtifact
```

If content is simple text, store as `str`. If structured outputs such as image/file are mixed, store as `OutputContentPart[]`.

```text
OutputContentPart =
  output_text
  output_image
  output_file
  output_audio
  output_video
```

Use `output_*` part because stored shape is assistant output. Lowerer converts to `input_text`, `input_image`, `input_file`, etc. for target API when building next model input.

`attachments` are Exchange refs for files assistant generated or referenced so UI can render. UI should render using only `content + attachments` without understanding `native_artifact`.

`native_artifact` is required because `assistant_message` originates from adapter/model output.

### 8. Canonical reasoning payload

`reasoning` is canonical payload for reasoning/thinking artifact exposed by provider.

```text
reasoning
  text: str | null
  summary: str | null
  native_artifact: NativeArtifact
```

`text` and `summary` are distinct.

```text
text
  content actually exposed by provider as reasoning/thinking text

summary
  content provider gave as separate reasoning summary field/event
```

Cross-model lowering drops both `text` and `summary`. Neither is converted to assistant/user/system message. Raw pass-through through `native_artifact` may be allowed only for same-native replay.

Provider-specific encrypted reasoning payload is not promoted to v1 canonical field. If needed, keep only inside `native_artifact.item`.

### 9. Separate system reminder and system error

`system_reminder` and `system_error` are separate canonical events.

```text
system_reminder
  text

system_error
  content
  severity?
  recoverable?
  reset_suggested?
```

Reasons:

- `system_reminder` is operational message rendered as XML in model input.
- `system_error` is state UI uses to decide execution failure, recovery, reset action, etc.
- Merging as `system_note(category=...)` makes exact event-shape rendering harder for clients.

### 10. Tool call/result is represented as common canonical event

Provider-executed tool with output is treated as call/result pair like client function tool.

Top-level kinds remain separated.

```text
client_tool_call
client_tool_result
provider_tool_call
provider_tool_result
```

Meaning:

- `client_*`: tool executed by azents application/runtime.
- `provider_*`: hosted tool executed server-side by model provider such as OpenAI, Anthropic, Google.

Rules:

- Provider tool with output is stored as canonical event like normal tool result.
- Azents does not re-execute provider tool during resume/retry.
- Provider raw artifact pass-through is considered only for same-native replay.
- Cross-model continuation lowers canonical tool call/result into target native format.
- Common shape is aligned, but executor identity is distinguished by canonical kind.

Canonical tool call payload:

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

Canonical tool result payload:

```text
client_tool_result
  call_id: str
  name: str
  output: str | OutputContentPart[]
  status: completed | failed | interrupted
  attachments: Attachment[]

provider_tool_result
  call_id: str
  name: str
  output: str | OutputContentPart[]
  status: completed | failed | interrupted
  attachments: Attachment[]
  native_artifact: NativeArtifact
```

### 11. `call_id` is canonical id and native ids are metadata

`call_id` is canonical identifier used to pair call/result. Native id is preserved inside native artifact.

Normalizer must guarantee:

- call/result pair uses same canonical call id.
- missing native id is replaced by deterministic generated id.
- provider id violating canonical id constraints is normalized.
- original native id is kept in native artifact.

This preserves continuity across providers while allowing same-native replay to use raw ids.

### 12. Missing tool result is synthetic interrupted result

If completed model output contains client tool call but execution cannot produce result because worker stopped, cancellation, shutdown, etc., append synthetic `client_tool_result(status=interrupted)` when closing run.

Reason: canonical transcript must not have dangling client tool call without result, because future lowering must preserve tool call/result pair.

### 13. Attachment is Exchange artifact ref, not native input part

`attachments` are not model-native `input_file`/`input_image` themselves. They are Exchange artifact metadata.

```text
Attachment
  uri: exchange://uploads/... | exchange://artifacts/...
  name
  media_type
  size_bytes
  thumbnail?
  text_preview?
```

Roles:

- UI preview/download
- session file list
- exposed as attachment manifest in next model input
- reference for generated artifact delivered to user

Do not merge `output` and `attachments`.

`attachments` is not common event field. It exists only in payloads that actually own files/artifacts.

```text
attachments available:
  user_message
  assistant_message
  client_tool_result
  provider_tool_result

attachments absent:
  reasoning
  client_tool_call
  provider_tool_call
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

`unknown_adapter_output` has no attachment. If normalizer understood a file, it should become `assistant_message` or `provider_tool_result`, not unknown.

### 14. Attachment rendering is unified as XML manifest

Attachment is not split into separate user input. Render it inside owning canonical event.

Rules:

- User input attachment is attached inside user message.
- Tool result attachment is attached inside same tool result output.
- Generated/provider artifact is attached inside owning event.
- URI/metadata is rendered only in XML manifest.
- Do not duplicate URI in body text.

Example:

```xml
Generated report.

<attachments>
  <attachment
    uri="exchange://artifacts/0123456789abcdef0123456789abcdef"
    name="report.pdf"
    media_type="application/pdf"
    size_bytes="184220"
  />
</attachments>
```

If tool result, entire content above goes inside native `function_call_output.output`.

### 15. Generated image/file becomes artifact at output normalizer stage

Image, audio, video, file generated by model are handled at adapter output ingestion stage, not lowerer stage.

```text
provider native response
  -> ModelOutputNormalizer
  -> extract generated bytes/file ref
  -> create Exchange artifact
  -> create canonical event
  -> append to event store
```

Default direction in new canonical design is to normalize as provider-origin tool call/result rather than old `GeneratedImage`-specific event.

```text
provider_tool_call
  name: image_generation

provider_tool_result
  call_id: ...
  output: ...
  attachments: [...]
```

If provider stream has no explicit call item and only result item, normalizer creates synthetic `provider_tool_call`. Canonical transcript preserves generated artifact as call/result pair.

### 16. Builtin/provider tool policy

Provider hosted tool enters request as `BuiltinToolSpec`.

```text
BuiltinToolSpec
  name: str
  config: dict
  required: bool
```

AdapterLowerer decides support based on target adapter/provider/model capability.

```text
supported:
  include as native hosted tool in request

unsupported + required=false:
  omit from request

unsupported + required=true:
  fail before run start with system_error
```

Client tool fallback is used only when explicitly configured. Hosted tool unsupported does not automatically fall back to client tool.

Rules:

- Provider tool is executed by provider, not re-executed by Azents.
- Provider tool output is stored as `provider_tool_result`.
- Provider tool raw is preserved in `native_artifact`.
- Cross-model continuation converts canonical provider tool call/result to possible native format by target lowerer.
- If target does not support that hosted tool transcript, degrade to normal assistant/tool transcript.

Image generation is considered provider hosted tool. Supported adapter creates `provider_tool_call` / `provider_tool_result`; output artifact is exposed as attachments. If unsupported, omit or fail run depending on `required`.

Provider-specific hosted tool stabilization is excluded from blocking scope of this ADR and tracked separately. Broken current builtin tool behavior is not prerequisite of clean runtime design.

### 17. Generated output original is stored in DB canonical event within size limit

Model/tool-generated image/file output stores original part directly in canonical `output` within size limit. Exchange artifact is also created and attached as `attachments`.

```text
DB canonical transcript:
  output = original Responses-compatible output, may include base64
  attachments = Exchange artifact refs

Object storage:
  artifact original bytes
```

This reduces worker restart window. If Exchange artifact creation fails, DB original can repair it within size limit.

Required limits:

```text
max_inline_artifact_bytes = 8 MiB
max_event_json_bytes = 16 MiB
max_total_output_bytes_per_event = 24 MiB
```

Meaning:

```text
max_inline_artifact_bytes
  per artifact original bytes

max_event_json_bytes
  entire JSON-serialized event size

max_total_output_bytes_per_event
  sum of original bytes for all output parts in one event
```

Base64 is about 1.33x larger than original bytes, so event JSON limit is larger than inline artifact limit. Private v1 starts with these values and lowers them if DB/latency issues appear.

On exceed:

- do not store inline original
- if artifact store succeeds, store attachment + placeholder
- if artifact store fails, store failed marker/placeholder

Policy by artifact storage result:

```text
case 1: inline possible + Exchange store success
  output: original parts
  attachments: [exchange ref]
  status: completed

case 2: inline possible + Exchange store failure
  output: original parts
  attachments: []
  status: completed
  record system_error or warning metadata so repair is possible

case 3: inline exceeded + Exchange store success
  output: placeholder part
  attachments: [exchange ref]
  status: completed

case 4: inline exceeded + Exchange store failure
  output: artifact unavailable placeholder
  attachments: []
  status: failed for tool/provider result
  system_error append
```

No separate status such as `completed_with_warning`.

If generated image/file is primary output of tool/provider result and both inline storage and Exchange storage fail, store `status=failed`. If assistant text was generated normally but only additional attachment storage failed, store `assistant_message` and append separate `system_error`.

### 18. Model input build is split into pre-filter, adapter lowerer, post-filter

Model input build pipeline passes canonical pre-filter first, then adapter-specific lowerer creates native request.

```text
canonical DB rows
  -> PreLowerFilterPipeline
       canonical -> canonical
       DB mutation allowed
       adapter agnostic
  -> AdapterLowerer
       canonical -> adapter native request
       adapter specific
       model capability aware
  -> PostLowerFilterPipeline
       adapter native request -> adapter native request
       adapter specific
       no DB mutation
```

Pre-lower filter handles canonical transcript. DB mutation is allowed to avoid rebuilding costly lifecycle transformations every request. Examples:

- image downsize / old image placeholder replacement
- old large tool observation masking
- replacing large inline payload with attachment manifest + placeholder

Even if Pre-lower filter modifies DB, Exchange artifact original and attachment ref must be preserved. It may reduce canonical payload for model input, but must not break UI/download/source artifact access.

AdapterLowerer must know target adapter native format, e.g.:

```text
LiteLLMResponsesLowerer
OpenAIResponsesLowerer
AnthropicMessagesLowerer
```

Canonical schema and pre-lower filter remain adapter agnostic. When switching adapter from LiteLLM Responses to official OpenAI client, Anthropic native client, any-llm, etc., replace lowerer/post-filter/normalizer/adapter implementation.

`compat_key` raw pass-through is final decision of AdapterLowerer. If target lowerer compat key equals `native_artifact.compat_key`, opaque raw item can be inserted into native request as-is. Otherwise rebuild target native shape from canonical fields.

Post-lower filter is final guardrail for adapter native request. It performs last-mile truncation, native schema cleanup, request size guard for provider/token/context size, but does not mutate DB.

Adapter protocol:

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

`ModelAdapter` must not know canonical. It is transport wrapper taking native request and emitting native stream event.

`AdapterOutputNormalizer` knows canonical. It promotes native stream/completed response to canonical event.

Streaming durable policy:

```text
on_stream_event -> UI projection only
on_completed    -> durable canonical events
```

Adapter with no completed response and only stream item done can assemble completed item with accumulator inside normalizer. Responsibility boundary remains same.

### 19. Capability-based unsupported modality conversion is lowerer responsibility

Conversion based on target model capability is core responsibility of AdapterLowerer, not pre-filter.

Examples:

```text
audio input unsupported -> text placeholder + attachment XML
video input unsupported -> text placeholder + attachment XML
image input unsupported -> text placeholder + attachment XML
file input unsupported  -> text preview/import instruction + attachment XML
```

Reason: target provider/model capability is known when native input is built.

Separation:

```text
TranscriptLowerer
  - canonical event -> adapter native request conversion
  - capability-based part conversion
  - unsupported modality degradation
  - canonical call/result -> native tool call/result conversion
  - final raw artifact pass-through decision

PreLowerFilter
  - old image/file reduction
  - long tool output masking
  - large inline payload replacement
  - DB mutation if needed

PostLowerFilter
  - adapter native request size guard
  - last-mile truncation
  - no DB mutation
```

### 20. Compaction does not delete; it moves model_input_head_event_id

Compaction does not delete existing events. Transcript remains append-only, and starting point for LLM call is managed as mutable pointer on session.

```text
AgentSession
  model_input_head_event_id: str | null
```

Meaning:

```text
null
  lower from beginning of session.

<compaction_summary event id>
  lower from that compaction_summary.
  Previous events remain in DB/UI/debug history but are not included in model input by default.
```

Model input load must include head, so use `>= model_input_head_event_id`.

```text
events = load where session_id = ? and id >= model_input_head_event_id order by id asc
```

On compaction success:

```text
1. append compaction_marker(status=started, compaction_id)
2. choose summary target range by existing policy
3. append compaction_summary(compaction_id, content, covered_until_event_id)
4. update AgentSession.model_input_head_event_id = compaction_summary.id
```

On compaction failure, append only `compaction_marker(status=failed, compaction_id, error)` and do not move `model_input_head_event_id`.

### 21. Compaction timing and policy keep existing behavior

Existing code policy:

- `max_input_tokens` uses model capability first; if absent use LiteLLM model info; otherwise fallback `128_000`.
- auto compaction trigger threshold is `max_input_tokens * 0.9`.
- protected region is `max_input_tokens * 0.3`.
- summary max tokens is `max_input_tokens * 0.1`.
- fallback budget for summary model failure/empty response is `threshold * 0.25`.
- old large tool observation masking protects latest 2 completed runs.
- observation masking target is output length `> 2_000` chars, preserving head `1_200` chars and tail `600` chars.

Automatic compaction runs in input build pipeline just before model call. Same as existing `CompactionFilter`, no compaction if estimated input token is below threshold.

Existing auto compaction reduced only current model call input with in-memory summary and left DB persistence to separate engine path. New structure appends `compaction_summary` and moves `model_input_head_event_id` on successful auto compaction so next call also uses same compacted view.

Manual compact command works as force compaction like before.

```text
force compact:
  protection = 0
  summary target = all model-visible transcript after current model input head
  on success model_input_head_event_id = new compaction_summary.id
```

Automatic compact is two-step as before:

```text
1. If estimated tokens after Pre-lower observation masking are below threshold, skip summary
2. If still over, summarize old events outside protected region
```

Boundary selection follows existing behavior:

- region within protected token budget from latest event is preserved.
- turn crossing boundary is included in summary target.
- if protected region can exceed threshold, cap with `max_protection=threshold`.
- if boundary cannot be found, fallback to force compaction.

Summary rendering policy:

- user message as `[User]`
- assistant text as `[Assistant]`
- tool call as `[Tool Call: name(arguments)]`
- tool result as `[Tool Result]`, but use long output only up to 2,000 chars
- reasoning text can be included as `[Reasoning]`
- previous compaction summary as `[Previous Summary]`
- exclude turn/run marker, compaction marker, subagent marker, generated artifact marker, error, unknown item from summary rendering

Summary model call preserves intent of existing prompt:

- summarize goals/instructions/findings/completion/relevant files so next agent can continue.
- output only summary, do not answer questions in conversation.
- use `compaction_provider/model` if present; otherwise current request provider/model.

Fallback summary policy also preserved:

- if summary model exception or empty response, include `COMPACTION_FAILURE_NOTICE`.
- fallback preserves recent rendered context within budget.
- fallback may be treated as successful summary; in that case head pointer moves.

### 22. Compaction lifecycle is linked by compaction_id

`compaction_marker` and `compaction_summary` are separate canonical events, but events for same compaction job are linked by `compaction_id`.

```text
compaction_marker
  compaction_id: str
  status: started | failed
  reason?
  error?

compaction_summary
  compaction_id: str
  content: str
  covered_until_event_id?
```

UI can merge started marker and summary/failure marker into one compaction job with `compaction_id`.

Do not delete start event on completion as old `COMPACTION_STARTED` did. New transcript is append-only log; lifecycle state is represented by additional events and session head pointer.

`compaction_summary` is completed artifact containing summary content that can enter model input. Lifecycle states such as `started` / `failed` belong in `compaction_marker`, not summary.

### 23. Subagent lifecycle splits start/end events

Subagent execution has separate canonical events `subagent_start` and `subagent_end`, linked by `subagent_run_id`.

```text
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
```

Subagent is not absorbed only as `client_tool_call` / `client_tool_result`. Subagent requires explicit canonical events because UI must render separate session link and lifecycle.

`subagent_start` and `subagent_end` have different payload meanings. Start expresses execution start and target link; end expresses result/failure/interruption. Therefore do not merge into single `subagent_marker(status=...)`.

UI merges start/end into one subagent execution using `subagent_run_id`.

### 24. Marker payload

Marker payloads use these shapes.

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
```

`turn_marker` records usage for model step/turn. `run_marker` is end boundary of full user-triggered run. Both have `run_id` so RunExecutionState can be linked to transcript row.

### 25. Streaming delta is not durable canonical event in v1

Durable partial text storage is deferred to later design.

Durable canonical transcript unit in v1 is completed native output item. Streaming delta is emitted only as UI projection event.

```text
StreamProjectionEvent
  content_delta
  function_arguments_delta
  reasoning_delta
  tool status delta

CanonicalEvent
  completed message
  completed tool_call
  completed tool_result
  usage/run markers
```

Future extension may introduce `CanonicalDraftEvent(status=partial|completed|interrupted)`.

### 26. Introduce Azents-owned RunExecutionState

Because SDK `RunState` is not used in final structure, azents-owned run state is needed.

v1 does not target replaying SDK internal state. It focuses on completed event boundary and active tool call tracking. `status` and `phase` are enums.

```text
AgentRunExecution
  run_id
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
  last_completed_event_id: str | null
  phase_started_at
  active_model_step_id: str | null
  active_tool_calls: list[ActiveToolCall]
  stop_requested: bool
  error: str | null
  updated_at

ActiveToolCall
  call_id: str
  name: str
  arguments: str
  started_at
  background: bool
```

Semantics:

- `last_completed_event_id` is resume/checkpoint basis.
- `phase` is operational/recovery judgment and UI activity source. Transcript source of truth is canonical event.
- Stop request sets `stop_requested=true`, `status=stopping`.
- When stop is applied and exits normally, append `run_marker(status=stopped)`.
- On worker restart detection, stale run with `status=running|stopping` is closed as `interrupted`.
- If foreground call remains in `active_tool_calls`, append synthetic `client_tool_result(status=interrupted)`.
- If worker dies during model streaming, no completed item exists, so durable transcript does not add assistant item. Partial durable storage is later design.
- Agent running indicator turns on in `waiting_for_model | streaming_model`.
- Tool activity UI uses `executing_tools` and `active_tool_calls`.
- `ActiveToolCall.arguments` can be stored as raw JSON string in state. Before UI publish, apply redaction/summarization based on tool schema or policy.

On worker restart, active foreground tool is closed with interrupted tool result by default. Do not auto-rerun tools without clear idempotency.

Background task recovery requires separate durable registry design.

## Existing normalization rules to preserve

Legacy raw LiteLLM code and SDK compatibility layer are removal targets, but bug-fix rules in them must move to new lowerer/normalizer tests.

Rules to preserve:

- tool call id length/character normalization
- guarantee call/result pair uses same normalized id
- malformed tool arguments sanitize
- synthetic result correction for missing tool output
- stable merge key injection for stream function args delta
- same-native raw artifact pass-through condition check
- cross-model reasoning drop
- provider metadata stripping
- provider-specific tool schema sanitization
- unsupported media degradation
- observation masking/head-tail truncation
- generated image/file attachment creation
- Exchange attachment XML manifest rendering

## Additional research result on 2026-05-27

### LiteLLM Responses API does not fully hide provider differences

LiteLLM docs describe `/responses` as following OpenAI Responses API spec and provide examples for OpenAI, Anthropic, Vertex AI, Bedrock, Gemini, etc. But implementation splits into two major paths.

- providers with native Responses config:
  - OpenAI, Azure, OpenAI-like, some hosted/provider-specific responses adapters
  - convert provider stream chunk directly to `ResponsesAPIStreamingResponse` type
- providers without native Responses config:
  - lower `responses` request to chat completion request, then synthesize Responses-style output from completion result
  - bridge layer reconstructs function tool, tool output, web search options, image generation output

Therefore even if `litellm.responses()` is first adapter, azents canonical contract must not merely trust LiteLLM output and must re-validate in `LiteLLMResponsesOutputNormalizer`.

Required normalizer checks:

- create canonical event by completed output item.
- branch on `message`, `function_call`, `function_call_output`, `web_search_call`, `file_search_call`, `image_generation_call`, `mcp_*`, unknown output item.
- distinguish provider-specific fields promoted to canonical fields versus fields preserved only as native artifact.
- unless same-native replay, do not pass LiteLLM-synthesized raw item through as-is.

### Streaming event normalization must not assume OpenAI native order

OpenAI Responses stream generally has order:

```text
response.created
response.output_item.added
response.content_part.added
response.output_text.delta*
response.output_text.done
response.content_part.done
response.output_item.done
response.completed
```

LiteLLM native Responses path parses provider chunk into event model. Completion bridge path synthesizes Responses-style event from chat completion stream.

Observed bridge properties:

- tool call delta is synthesized from chat completion `tool_calls` delta into `response.output_item.added` / `response.function_call_arguments.delta`.
- if provider gives tool arguments all at once, LiteLLM splits into 10-char deltas.
- if no tool delta during stream and tool call exists only in final response, function call added/delta/done/item done events are synthesized late at stream end.
- reasoning content may be synthesized as `response.reasoning_summary_*` event.
- list values of provider-specific fields may accumulate during stream in cumulative last-value-wins way.

Conclusions:

- UI stream projection is best-effort delta.
- durable canonical event is created from completed item or completed response.
- tool call merge key should not trust only `output_index`; it needs correction rules by `call_id`/`item_id`/name.
- actual provider-specific event order needs golden traces from spike.

### Builtin tools span different layers by provider

Current azents builtin tools support `web_search`, `web_fetch`, `image_generation`. Existing SDK path converts differently by provider/model developer.

- OpenAI/ChatGPT OAuth:
  - SDK hosted `WebSearchTool`
  - SDK hosted `ImageGenerationTool`
- Google/Gemini:
  - `web_search_options`
  - `modalities=["text", "image"]`
  - exclusive restrictions with other builtin/toolkit
- Anthropic:
  - raw `web_search_20250305`
  - raw `web_fetch_20250910`
- fallback:
  - `web_search_options`
  - raw `image_generation`

Findings in LiteLLM Responses:

- `web_search`/`web_search_preview` are converted to `web_search_options` in completion bridge.
- `image_generation_call` may be synthesized from OpenAI native output or chat completion `message.images` as Responses-style `image_generation_call.result`.
- `file_search` uses emulated file search path unless OpenAI/Azure native support exists; this path disables streaming and creates synthesized response.
- MCP proxy path can automatically perform tool discovery/execution/follow-up call inside LiteLLM, conflicting with azents-owned tool loop principle.

Conclusions:

- In v1 clean runtime, provider hosted tool canonicalizes as `provider_tool_call` / `provider_tool_result`.
- LiteLLM MCP auto-execution does not fit azents-owned loop and is not adopted as v1 default path.
- `file_search` is not current azents builtin, but Responses adapter may auto-emulate it, so usage must be explicitly blocked or separately designed.

### Clean deletion impact

SDK production dependency is concentrated under `engine/sdk/**`, but external touchpoints remain.

Production import impact:

- `engine/deps.py`
  - `LitellmLLMClient`
  - `OpenAIEngineAdapter`
- `engine/commands.py`
  - `OpenAIEngineAdapter.compact()`
- `services/agent_runtime/__init__.py`
  - worker/run service receives `OpenAIEngineAdapter` by DI
- `worker/engine.py`, `worker/deps.py`
  - worker run loop expects `OpenAIEngineAdapter`
- `engine/tools/subagent.py`
  - subagent tool directly depends on `OpenAIEngineAdapter`
- `engine/events/formatters.py`
  - depends on `agents.items.TResponseInputItem` type
- `engine/compaction.py`
  - depends on SDK compaction summary strategy
- `services/slack/format.py`, `services/discord/format.py`
  - only uses legacy `runtime.llm.render_message`

Conclusions:

- Removing `engine/sdk/**` alone is not enough.
- Change adapter public contract to new protocol first, then update worker/service/subagent/command accordingly.
- `runtime/llm.py` is legacy client but also contains `render_message`; before clean delete, move formatter helper to separate location or replace with new transcript renderer.

### Destructive cutover DB plan

Current DB already discarded legacy events and unified into single `events` table. `events.item` JSONB stores mixed SDK raw passthrough, and only `source_model` is separate column. `agent_runtimes` has `run_state`, `run_heartbeat_at`, `sdk_run_state`.

DB decisions needed for clean cutover:

- Existing SDK raw shape in `events.item` is discarded and not migrated.
- Under private service assumption, existing transcript/session/run state data is not migrated to canonical schema.
- Use shadow table cutover instead of in-place enum/schema change.
- Create new canonical tables with separate names, and when runtime switch is ready, drop old tables and rename new tables to canonical names.
- `source_model` alone is insufficient for same-native replay decision. New canonical row or metadata needs at least `adapter`, `provider`, `model`, `native_format`, `schema_version`.
- Remove `sdk_run_state` or replace with new `agent_run_executions`/`run_execution_state`.
- `AgentRuntimeRunState(idle/running)` is runtime occupancy level and insufficient to represent agent execution checkpoint.

Recommendation:

- v1 uses destructive cutover and discards existing transcript/session.
- Cutover uses shadow table method.
- Explicitly set new canonical transcript schema version at same time.
- Do not create transition continuing SDK `RunState` JSON.

Cutover outline:

```text
1. Create new canonical events/sessions/runs shadow tables
2. Prepare new runtime to operate against shadow tables
3. Drain active workers just before deploy
4. Drop or archive old events/session/run_state tables
5. Rename shadow tables to canonical table names
6. Enable new runtime
```

Existing data is not migration target. Keep only as operational backup/archive if needed.

Shadow schema draft follows existing RDB model pattern.

Common patterns:

- primary key uses `sa.String(32)` UUID7 hex.
- rows needing chronological order use `ORDER BY id ASC`.
- timestamps use `TimeZoneDateTime` and `server_default=sa.func.now()`.
- structured payload uses PostgreSQL `JSONB`.
- enum follows existing SQLAlchemy `ENUM(..., create_type=False, values_callable=...)` pattern.
- final table names are simple: `events`, `agent_sessions`, `agent_runs`.
- shadow table names use temporary suffix only during migration and are renamed at cutover, e.g. `events_next` -> `events`.

`events` replacement:

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

`agent_sessions` replacement keeps existing `agent_sessions` columns and adds model input head.

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

indexes:
  ix_agent_sessions_workspace_id(workspace_id)
  ix_agent_sessions_agent_id(agent_id)
  ix_agent_sessions_agent_runtime_id(agent_runtime_id)
  uq_agent_sessions_runtime_active(agent_runtime_id)
    where status = 'active'
```

`agent_runs` replaces SDK `RunState` JSON.

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

`model_input_head_event_id` logically references event id in same session. Physical FK decision is left to implementation because shadow table rename and compaction head update ordering may be simpler without FK.

### Provider-specific spikes needed

Items not confirmable only by documentation/code research:

- OpenAI native Responses stream trace for tool call + image generation + web search
- Anthropic via LiteLLM Responses completion bridge tool call/result roundtrip trace
- Gemini/Vertex image output and multimodal tool output trace
- Bedrock tool arguments streaming shape
- final output item shape for provider hosted tool result
- whether unsupported modality input is rejected by provider or transformed by LiteLLM
- which durable marker to leave when stream ends by cancellation/timeout without final `response.completed`

These spikes are for golden trace collection, not implementation.

## Considered Options

### A. Keep Agents SDK + reinforce it

Keep SDK Runner and only reinforce partial durable storage, compatibility filter, state storage.

Rejected reasons:

- SDK still owns tool loop and checkpoint in practice.
- Transcript source of truth stays tied to SDK/OAI raw shape.
- It is hard to guarantee cross-model continuity as explicit azents contract.

### B. Canonical transcript + azents-owned loop + native lowerer

Accepted.

Pros:

- continuity contract is clear when model/provider/client changes.
- SDK and legacy LiteLLM loop can both be removed.
- LiteLLM Responses can be first adapter while core is not tied to LiteLLM.
- tool loop, run state, artifact policy are owned by azents domain.

Cons:

- implementation scope is large.
- tool loop, stop/cancel/resume, provider compatibility, subagent/background parity must be implemented directly.

### C. pre-SDK raw LiteLLM rollback

Rejected reasons:

- Current event model differs from pre-SDK event model.
- It is closer to new loop implementation than simple revert.
- It does not match clean-state goal.

## Outcome

Adopt B.

Implementation direction is clean-state agent execution replacement, not rollback.

```text
canonical transcript
  + LiteLLMResponsesOutputNormalizer
  + LiteLLMResponsesLowerer
  + azents-owned tool loop
  + azents-owned RunExecutionState
  + destructive cutover
```

## References

- [events-260428/ADR](./events-260428-events-table-as-truth.md): events table single truth
- [function-260429/ADR](./function-260429-function-call-output-item.md): function call output item split
- [sandbox-260525/ADR](./sandbox-260525-sandbox-redesign.md): Sandbox system redesign
- GitHub issue: #4074
- 2026-05-27 Codex design transcript

## Migration provenance

- Historical source filename: `0039-agent-execution-transcript-normalization.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
