---
title: "Event transcript and model input"
created: 2026-11-04
tags: [wiki]
---

# Event transcript and model input

Owns durable event types, model-visible history and model-turn provenance. Session identity, transport projections and context compaction are separate connected contracts.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Conversations and events](../domain/conversation.md)
- [Session mailbox and input admission](mailbox.md)
- [Context compaction](../flow/context-compaction.md)
- [Chat resynchronization](../flow/chat-session-resync.md)
- [Agent execution](../flow/agent-execution-loop.md)
- [Run state and operation snapshots](runs.md)
- [Model selection and prepared inference](../models/selection.md)

## Durable event types and visibility

Event transcript is the durable source of truth for model/tool/session output. Event payloads are
stored as JSONB and validated by event kind.

The typed event registry accepts these kinds:

- `user_message`
- `assistant_message`
- `reasoning`
- `client_tool_call`
- `client_tool_result`
- `provider_tool_call`
- `turn_marker`
- `run_marker`
- `interrupted`
- `compaction_marker`
- `compaction_summary`
- `system_reminder`
- `goal_continuation`
- `goal_updated`
- `agent_message`
- `external_channel_message`
- `external_channel_continuation`
- `scheduled_task_trigger`
- `scheduled_task_continuation`
- `scheduled_task_result`
- `routine_judgment`
- `routine_trigger`
- `routine_continuation`
- `routine_notification`
- `action_message`
- `action_execution_result`
- `skill_loaded`
- `goal_briefing`
- `system_error`
- `unknown_adapter_output`

An accepted stored kind is not a promise that current producers emit it. In particular,
`action_message` remains a readable typed event shape, while current TurnAction promotion uses
the side effects described below. Scheduled and Routine event lifecycles belong to
[Scheduled Tasks](../domain/scheduled-task.md) and [Routines](../domain/routine.md);
External Channel ingress and continuation belong to
[External Channels](../domain/external-channel.md).

Turn-marker token usage stores normalized input/output/total/cache/reasoning counters,
nullable `cost_usd` and optional typed `cost_provenance`. Native raw usage and hidden
parameters are transient normalization/pricing inputs, not durable usage fields.
Typed projections omit those extras from existing records without rewriting their physical
JSONB storage; historical receipt cleanup requires a separate approved operation.
Known estimates identify the selected provider/model, applicable tier and captured source
snapshot/hash/key/estimator version. Native reported charges use a separate
`provider_reported` method and do not acquire price-source provenance. Old amounts without
that field remain unlabeled; history is not rewritten and existing cost presentation is unchanged.

`agent_message` records agent-to-agent mailbox delivery in the target session. Instruction payloads use
`message_kind` `spawn_agent`, `send_message`, or `followup_task` and store source/target
`SessionAgent` ids, canonical paths, and content. Terminal payloads use `message_kind = agent_result`
and additionally store source Run id/index/status plus the nullable source terminal event id. Shared
provider lowering renders instructions as `NEW_TASK` or `MESSAGE` envelopes and terminal payloads as
`AGENT_RESULT` envelopes. Terminal content is the Run's user-safe result projection or a fixed status
fallback; internal exception text and provider diagnostics are not mailbox content.

A terminal `agent_result` remains unread while merely enqueued or observed by `wait`. Promotion
into the direct parent's durable transcript validates the actual source child and terminal Run metadata,
then advances the child's observation cursor monotonically in the same transaction that appends or
deduplicates the event and deletes the mailbox envelope. After commit, the execution layer publishes a
`subagent_tree_changed` invalidation for every cursor that advanced.

`action_message` is a mailbox kind for user-selected TurnActions, not a newly appended transcript
event. `skill` actions load Skill context by appending `skill_loaded` and an optional normal
`user_message`. `create_git_worktree` actions create mailbox-item-keyed live execution state before the
source mailbox envelope is consumed. `action_execution_result` is a durable transcript event containing the complete terminal action
execution projection after a worktree action completes, fails, or is cancelled; it lets history
reloads render operation logs without treating them as model input or ordinary chat bubbles.

`skill_loaded` records a Skill turn action side effect. Its payload stores the Skill display name,
exact `skill_path`, full Skill body, original user action message, content hash, source label, and
relative hint. Model lowering injects `skill_loaded` as a required user-role instruction to read and
follow the embedded Skill body; the original user action message is promoted as the following normal
`user_message` event when non-empty. The UI renders `skill_loaded` as an expandable control event, while the consumed Skill mailbox item
does not create a duplicate action-message bubble.

`system_error` payloads may include optional user-safe failed-run metadata under `failure`. The
metadata identifies terminal failed-run output, provider/runtime presentation kind, finalization
reason, retry counts, last error type, diagnostic retryability/failure code, and bounded attempt
summaries. A provider-authored scalar message may be stored only after the common deterministic
bounding and secret-redaction boundary. Stack traces, credentials, headers, cookies, request/model
output, arbitrary raw provider bodies, raw stream frames, and SDK serialization are not stored in
durable transcript payloads.

Attachments are payload-specific, not event-common. Client and provider tool delivery attachments are
canonical `AttachmentOutputPart` values inside semantic/result output; tool payloads do not own a
parallel top-level attachments field. Tool output is either a plain string or an ordered typed-part
array containing `OutputTextPart`, `AttachmentOutputPart`, `ArtifactOutputPart`, or `FileOutputPart`;
the serialized discriminators are `text`/`output_text`, `attachment`, `artifact`, and `file`.

One completed Brave image-search `client_tool_result` may contain multiple ordered
ModelFile-backed `FileOutputPart` values and independent Exchange
`AttachmentOutputPart` values alongside bounded text. Each selected thumbnail
has a distinct output index under the same call identity; unselected or
unavailable thumbnails included within the bounded text budget retain
attributable URLs rather than fabricated files. Later entries may be omitted
with a count when the text budget is exhausted.
File parts are for later model input, while attachment parts are visible and
downloadable to the participant. Neither stores image bytes or credentials in
the event. Provider-hosted image generation retains its own single-image call
contract.

Every `client_tool_call` and `client_tool_result` persists a closed `wire_dialect`: `json_function`
or `plaintext_custom`. Call `arguments` remains the exact decoded provider input and must be
interpreted only through that stored dialect. Result creation copies the dialect from its admitted
call; a call/result mismatch is rejected rather than repaired or relabeled. Legacy persisted client
call, result, and active-call records without the additive field are read only as
`json_function`; newly written records contain an explicit value. Null, unknown, and malformed values
do not receive that legacy interpretation.

Event IDs are the single durable append, audit, UI, and model-visible order within a Session.
History pagination, future model input, revert ranges, fork selection, and cleanup cursors all compare
the fixed-width UUIDv7 hexadecimal IDs. Event append does not allocate a separate Session-scoped
logical order. Compaction keeps append-only storage while presenting future model input from a single
`compaction_summary` head event.

Every `provider_tool_call` stores required provider-neutral semantic content under
`payload.semantic`: nullable readable `input`, model-visible `output`, and typed `references`.
References carry kind `url | file | other`, nullable URI/title/excerpt, and stable string metadata.
Tool-created delivery files are `AttachmentOutputPart` values in `semantic.output`; model replay files
are `FileOutputPart` values in the same output. Adapters normalize provider-exposed semantic content
before persistence, apply canonical field and collection bounds, and keep provider-only fields inside
the opaque native artifact. The persisted contract does not use top-level provider-tool `arguments`,
`output`, or `attachments` fields.

`ProviderToolCallPayload.status` is the provider-neutral lifecycle state `running`, `completed`,
`failed`, `cancelled`, or `interrupted` when known. Live provider-tool calls carry the latest observed
canonical state. Durable calls carry the terminal status normalized from the one provider-native item;
historical events may omit it. Provider-native stage strings remain confined to the adapter native
artifact.

`NativeArtifact.item` is adapter-native opaque payload. Event core does not interpret it.
Same-native pass-through is allowed only when the compat key matches exactly:

```text
adapter:native_format:provider:model:schema_version
```

Official OpenAI SDK Responses artifacts use adapter identity `openai`, native format `responses`,
and schema version `1`. Pydantic AI model-layer artifacts use adapter identity `pydantic_ai`, native
format `model_messages`, the exact raw provider/model identity, and schema version `1`.
Historical LiteLLM Responses artifacts retain their original `litellm` identity and are not
relabeled or replayed by a new adapter. A mismatch always reconstructs input from canonical events. Provider-tool
fallback uses one deterministic readable rendering of semantic input, output, references, excerpts,
and stable metadata rather than inspecting native artifacts. This includes forward cutover from old
LiteLLM artifacts and a compatible code-version rollback reading artifacts owned by another adapter;
cross-adapter objects are never replayed as though they shared schema ownership.

Client-tool native artifacts are subordinate to the canonical stored dialect. A same-native custom
artifact is replayable only when the current route can represent that custom dialect and the native
item type matches it; JSON-function artifacts have the analogous function item contract. When a later
route cannot represent a completed custom call/result pair, lowering preserves the durable events but
emits bounded, explicitly non-executable historical context. It omits the custom input, keeps only a
bounded result preview when present, does not create active ownership, and never converts the pair to
the other dialect. A native function/custom output item without an earlier matching-dialect call is
dropped before provider dispatch; an incompatible historical custom result remains only as its bounded
non-executable projection.

A completed provider-hosted `image_generation` item uses one durable provider-call shape. Its
`semantic.output` contains both a ModelFile-backed `FileOutputPart` and the independently stored
Exchange original as an `AttachmentOutputPart`. Provider Base64, decoded bytes, and native `result`
fields are transient only and are excluded from event payloads, native artifacts, REST/WebSocket
projections, and frontend state. xAI Imagine retains client tool call/result ownership while storing
the same two output-part kinds in the durable client result; credentials and transient bytes remain
excluded. Same-native lowering reconstructs the provider-native image result from the ModelFile in
request-local memory and emits the bounded Exchange URI context separately. An incompatible adapter
or model, and every later-model use of a client-generated result, lowers the file through the normal
rich-image path or an explicit bounded unavailable-image placeholder while retaining attachment URI
metadata.

## Execution transcript and model-turn markers

### Append identity and deduplication

[`EventTranscriptRepository.append`](../../../../python/apps/azents/src/azents/repos/agent_execution/__init__.py)
validates and serializes the payload for its kind. A non-null `external_id` is a
Session-scoped idempotency key backed by the partial unique index on
`(session_id, external_id)`. Concurrent keyed appends use insert-on-conflict-do-nothing:
the existing event is returned with its original ID and payload, rather than replaced by the
retry's content. Callers must choose keys that identify the same logical event; a key collision
is not a content-equality check. An append without an external ID creates a separate UUIDv7 event.
This does not guarantee exactly-once provider execution or deduplicate arbitrary model output.

Normal inserts advance Session projections in the caller's transaction; the deferred-projection
append variant lets its composing repository batch that work. Neither low-level append method
commits independently. Model-input reads exclude reverted events, order by event ID and include
the selected head event when a head is supplied. The head changes the input view, not append order.

### Usage and immutable applied provenance

[`EngineEventMutationRepository.append_turn_marker`](../../../../python/apps/azents/src/azents/repos/engine_event_mutation.py)
appends a `turn_marker` only when normalized usage is present. Its payload stores the Run ID and
usage plus the prepared call's optional public applied profile, physical route and effective
context/automatic-compaction limits. The call carries its turn-local `SessionInferenceState`;
marker creation does not query a later mutable Session value. Explicit null reasoning effort
in an applied profile survives serialization. Historical or other callers without inference state
may have usage-only markers; absence of a marker does not prove that no model output was admitted.

The production model-output path passes `prepared.call.inference_state` to
[`EngineOutputOperationRepository.admit_model_output`](../../../../python/apps/azents/src/azents/repos/engine_output_operation.py).
Under the execution owner fence, normalized events, the optional usage marker, output metadata,
the current system-prompt analysis snapshot, retry-state clearing and any active client-tool
ownership/phase update commit as one group. A late error or cancellation rolls back that group.
Events and live phase updates are published after admission returns. The system-prompt analysis
snapshot is separate from the marker payload. See [Run retry boundaries](runs.md#execution-state-and-terminal-boundaries)
and [model snapshot preparation](../models/selection.md#runtime-resolve).

Native replay compatibility and canonical fallback are described above under
[durable event types and visibility](#durable-event-types-and-visibility).

Cross-model lowering drops reasoning text and summary. Reasoning is preserved as event
`reasoning` for UI/audit and is not converted into assistant/user/system content.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/engine/events`](../../../../python/apps/azents/src/azents/engine/events)
- [`python/apps/azents/src/azents/services/chat`](../../../../python/apps/azents/src/azents/services/chat)
