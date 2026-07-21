---
title: "Chat Protocol Uses Canonical Event History/Live API"
created: 2026-06-04
tags: [architecture, backend, frontend, engine, chat, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: chat-260604
historical_reconstruction: true
migration_source: "docs/azents/adr/0047-chat-protocol-history-live-state.md"
---

# chat-260604/ADR: Chat Protocol Uses Canonical Event History/Live API

## Status

Accepted. This protocol decision was finalized after analyzing Chat UI instability causes and reviewing the draft of PR #4390.

## Background

Current Chat UI receives REST message list and WebSocket events with different schemas.

- REST `ChatMessageListResponse.items`
- REST `run_state`, `run_phase`, `input_buffers`, `active_tool_calls`
- WS `content_delta`, `reasoning_delta`, `function_call_delta`
- WS `run_started`, `run_phase_changed`, `run_complete`, `run_stopped`
- WS `input_buffered`, `input_buffer_deleted`
- canonical event transport

Because of this, frontend merges history and live state directly and resolves duplicate display/loss in reload, reconnect, tool backfill, and pending input cases by inference. The existing `/messages` endpoint mixes message UI projection and runtime/live state in one response contract, so if we keep it and add v2 fields, the same problem will repeat.

Azents already uses canonical events as the source of truth for durable transcript. Therefore, the chat screen contract should also align around canonical event transport.

## Decision

### 1. Remove `/messages` endpoint

The existing `GET /chat/v1/sessions/{session_id}/messages` list messages endpoint is removed in the final state. New APIs separate history and live.

- `GET /chat/v1/sessions/{session_id}/history`
- `GET /chat/v1/sessions/{session_id}/live`

During the stack transition, the legacy endpoint may temporarily remain for frontend migration, but before cleanup it must be removed from routes, OpenAPI schema, and generated client usage.

### 2. History API returns only persisted canonical events

History API paginates only durable events stored in canonical events table. It does not return UI message schemas such as `ChatMessageResponse`.

Events in history have these properties:

- persisted;
- mostly append-only;
- pageable;
- source of truth for model input lowering and audit/debug.

Examples are existing canonical event kinds: `user_message`, `assistant_message`, `reasoning`, `client_tool_call`, `client_tool_result`, `provider_tool_call`, `provider_tool_result`, `turn_marker`, `run_marker`, `compaction_marker`, `compaction_summary`, `system_error`, and so on.

### 3. Live API also uses canonical event transport

Live API returns a list of non-durable canonical event projections needed to restore current screen. Do not create a separate live schema.

Live event projection is not persisted history. Sources include Redis live event store, `input_buffers`, and `agent_runs`. API payload reuses canonical event transport union.

Examples:

- `input_buffers` row → non-durable `user_message` projection
- streaming assistant text → non-durable `assistant_message` projection
- streaming reasoning → non-durable `reasoning` projection
- tool argument draft/running operation → non-durable `client_tool_call` or provider tool projection
- compaction in progress → non-durable `compaction_marker` projection

When a persisted canonical event appears, the matching live projection is removed or ignored by client selector.

### 4. WebSocket uses only canonical event transport actions

WS does not deliver source-specific legacy events as chat UI contract.

Final WS actions are these three:

- `history_event_appended`: persisted canonical event append
- `live_event_upserted`: add/update non-durable canonical event projection
- `live_event_removed`: remove non-durable canonical event projection

Payload domain data is canonical event. `live_event_removed` id-only payload is a transport action, not a new domain schema.

### 5. Frontend renders two canonical event lists

Frontend state separates persisted `historyEvents` and non-durable `liveEvents`. Components do not directly interpret canonical events; they render only view models produced by selectors.

Selector rules:

- Persisted history event takes precedence over matching live event.
- Pending input is rendered as live `user_message`; when promoted persisted `user_message` arrives, remove live event.
- Streaming assistant/reasoning is rendered as live event; when finalized persisted event arrives, transition to history.
- Tool draft/running state is rendered as live event; terminal call/result pair is rendered as history.

## Rejected Directions

### Add v2 fields to existing `/messages`

Rejected. The existing endpoint is the central problematic contract mixing history/live/runtime state.

### Single `/messages/v2` endpoint

Rejected. History and live have different lifecycle and pagination semantics, so API paths should separate them.

### Separate live schema

Rejected. Since canonical event is the contract, do not create a live payload contract different from canonical event.

### Store streaming delta as persisted canonical event

Rejected. Streaming partials are not finalized history, and canonical event table remains durable transcript source.

### Keep frontend legacy event merging

Rejected. Reload/reconnect/tool backfill issues would continue to be solved by frontend inference.

## Consequences

### Expected Benefits

- REST and WS chat payloads align on canonical event contract.
- Drift between existing message UI schema and live state schema disappears.
- Screen can be restored after reload/reconnect by rereading history API and live API.
- Tool call/result, streaming handoff, and pending input promotion become simpler selector rules.
- Removing `/messages` mixed contract prevents later implementation from falling back into the same layering problem.

### Cost and Risks

- Backend must store and clean up non-durable canonical event projections in Redis.
- Mapping rules are needed to represent pending input and streaming/tool live projection as canonical event payloads.
- Frontend must move from `ChatMessageResponse`-centered load path to canonical event reducer/selector-centered path.
- Subagent session hook must also move to the same contract.
- Existing E2E uses legacy `input_buffered` and message list, so it must be strengthened around canonical event API.

## Related Documents

- [Chat canonical event history/live API design](../design/chat-260604-chat-protocol-history-live.md)
- `docs/azents/adr/events-260428-events-table-as-truth.md`
- `docs/azents/adr/execution-260527-execution-transcript-normalization.md`
- `docs/azents/adr/compaction-260530-compaction-logical-event-ordering.md`
- `docs/azents/design/frontend-chat-wire-envelope.md`

## Migration provenance

- Historical source filename: `0047-chat-protocol-history-live-state.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
