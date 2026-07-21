---
title: "Chat Live State Taxonomy Implementation Design"
created: 2026-06-10
updated: 2026-06-10
implemented: 2026-06-10
tags: [backend, frontend, chat, streaming, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: live-260610
migration_source: "docs/azents/design/chat-live-state-taxonomy.md"
historical_reconstruction: true
---

# Chat Live State Taxonomy Implementation Design

## Overview

Chat live state is not a single list, but composition of partial history and other live state. Current implementation mixes REST `/live` `items`, WebSocket `live_event_*`, and frontend `messages` in same path, causing assistant text/reasoning/tool call partial, input buffer, and run state to be handled as if they have same lifecycle.

This design implements [live-260610/ADR](../adr/live-260610-live-partial-history-taxonomy.md) and clearly separates live state subcategories in API and frontend state management. Existing aggregate live list contract is removed, and partial history plus input buffer are exposed as independent contracts.

## Requirements

### REQ-1: Live state API taxonomy

- Description: REST live snapshot must explicitly distinguish partial history and other live state.
- Related decisions: [live-260610/ADR-D1](../adr/live-260610-live-partial-history-taxonomy.md), [live-260610/ADR-D4](../adr/live-260610-live-partial-history-taxonomy.md), [live-260610/ADR-D5](../adr/live-260610-live-partial-history-taxonomy.md)
- Acceptance criteria:
  - `/live` response provides `partial_history.items`.
  - `/live` response provides input buffer projection separately as `input_buffers`.
  - `/live` response does not provide aggregate `items` field.
  - `run` and `session_run_state` remain as live control state as before.

### REQ-2: REST write snapshot taxonomy

- Description: REST write response snapshot must also reflect live taxonomy.
- Related decisions: [live-260610/ADR-D5](../adr/live-260610-live-partial-history-taxonomy.md), [live-260610/ADR-D8](../adr/live-260610-live-partial-history-taxonomy.md)
- Acceptance criteria:
  - `ChatWriteSnapshotResponse` provides `partial_history_events` and `input_buffer_events`.
  - `ChatWriteSnapshotResponse` does not provide aggregate `live_events` field.
  - frontend write response mapping uses only split fields.

### REQ-3: Managed live state reducer

- Description: frontend must handle WebSocket event as managed live state mutation, not UI append command.
- Related decisions: [live-260610/ADR-D6](../adr/live-260610-live-partial-history-taxonomy.md), [live-260610/ADR-D8](../adr/live-260610-live-partial-history-taxonomy.md), [live-260610/ADR-D9](../adr/live-260610-live-partial-history-taxonomy.md)
- Acceptance criteria:
  - partial history is managed as ordered collection.
  - Patch with same semantic key keeps existing position and updates only item.
  - REST snapshot apply and WebSocket patch apply use same live state reducer/helper.

### REQ-4: History/partial history composite

- Description: durable history and partial history must be managed as independent container outputs and statelessly composed only at render time.
- Related decisions: [live-260610/ADR-D10](../adr/live-260610-live-partial-history-taxonomy.md)
- Acceptance criteria:
  - durable history messages and partial history messages are kept as separate state.
  - Rendered `messages` is derived state that appends partial history after history with `useMemo`.
  - If same id exists on both sides, skip partial history item.

### REQ-5: Preserve partial lifecycle

- Description: live assistant/reasoning/tool partial must preserve partial lifecycle until converted to `complete` history item.
- Related decisions: [live-260610/ADR-D2](../adr/live-260610-live-partial-history-taxonomy.md), [live-260610/ADR-D3](../adr/live-260610-live-partial-history-taxonomy.md), [live-260610/ADR-D7](../adr/live-260610-live-partial-history-taxonomy.md)
- Acceptance criteria:
  - live partial history item renders as `status: "partial"`.
  - durable history item renders as `status: "complete"`.
  - tool call without result is classified as partial history candidate, but provisional delta without call id/name is not rendered.

## Decision Table

| ADR decision | Requirements |
| --- | --- |
| [live-260610/ADR-D1](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-1 |
| [live-260610/ADR-D2](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-5 |
| [live-260610/ADR-D3](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-5 |
| [live-260610/ADR-D4](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-1 |
| [live-260610/ADR-D5](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-1, REQ-2 |
| [live-260610/ADR-D6](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-3 |
| [live-260610/ADR-D7](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-5 |
| [live-260610/ADR-D8](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-2, REQ-3 |
| [live-260610/ADR-D9](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-3 |
| [live-260610/ADR-D10](../adr/live-260610-live-partial-history-taxonomy.md) | REQ-4 |

## Architecture

### Backend

REST `/live` returns only live taxonomy fields.

- `partial_history.items`: assistant-side live partial list to compose into chat timeline.
- `input_buffers`: pending user input buffer projection list.
- `run`: current run projection.
- `session_run_state`: authoritative session run state.

REST write snapshot provides same taxonomy.

- `partial_history_events`: partial history live projection list.
- `input_buffer_events`: pending input buffer projection list.
- `run`, `session_run_state`: existing control state.

Classification criteria:

- input buffer: `user_message` and `payload.metadata.live_projection == "input_buffer"`.
- partial history: live projection renderable in chat timeline and not input buffer.
- other live state: `run`, `session_run_state`, input buffer collection, future flags.

### Frontend

Session container has these source states.

- `historyMessages`: durable history container output.
- `liveState.partialHistory`: ordered partial history message collection.
- `liveState.pendingInputBuffers`: pending input buffer collection.
- `liveState.runPhase`, `liveState.sessionRunState`: control state.

Rendered `messages` is not separate source state.

- `messages = useMemo(() => mergeHistoryAndPartialHistory(historyMessages, liveState.partialHistory), [...])`
- merge appends partial history after durable history.
- partial id already in durable history id set is skipped.

WebSocket handler uses these reducer helpers.

- `replaceLiveStateFromSnapshot`
- `upsertPartialHistoryEvent`
- `removePartialHistoryEvent`
- `upsertPendingInputBufferEvent`
- `removePendingInputBuffer`
- `applyHistoryEvent`

## API

This implementation changes live state API contract. Existing aggregate `items` and `live_events` fields are removed, and backend schema is updated so OpenAPI generated client creates only split fields.

## Frontend Details

### Partial history semantic key

Initial implementation uses following semantic keys.

- assistant message: ideally `assistant:${event.payload.native_artifact?.item.content_index ?? event.id}`, but current generated response type holds payload as `Record<string, unknown>`, so read `native_artifact.item.content_index` best-effort.
- reasoning: `reasoning`
- tool call: `tool:${call_id}`
- fallback: `id:${event.id}`

When same semantic key arrives, existing order position is preserved.

### Detached browsing

In detached state, managed live state can keep updating, but composite messages do not include partial history. As existing behavior, only new activity chip is shown.

## Implementation Plan

1. Add [live-260610/ADR](../adr/live-260610-live-partial-history-taxonomy.md).
2. Add `partial_history`/`input_buffers` and write snapshot split fields to backend response schema.
3. Add frontend type/model helpers.
4. Reduce `useChatWebSocket` from source `messages` owner to managed live state patch callback.
5. Manage history messages and live state separately in `useChatSessionContainer`, and make composite messages derived state.
6. Promote spec by reflecting live taxonomy and composite invariant in `chat-session-resync.md`.
7. Run targeted backend/frontend tests and typecheck.

## Test Strategy

### Static/targeted checks

- Python: `cd python/apps/azents && uv run pyright`
- Python targeted tests:
  - `cd python/apps/azents && uv run pytest -vv src/azents/services/chat/input_buffer_test.py src/azents/services/chat/live_events_test.py src/azents/api/public/chat/v1/chat_api_test.py`
- Frontend: `turbo run typecheck --filter=@azents/web`
- Frontend lint/format if touched files require:
  - `turbo run lint --filter=@azents/web`
  - `turbo run format --filter=@azents/web`
- Generated client: `turbo run typecheck --filter=@azents/public-client`

### Product behavior verification

This change modifies chat runtime state merge model, so final QA must verify with E2E/chat live scenario.

Primary scenarios:

1. Streaming assistant text appears as partial and hands off without duplication when durable assistant message arrives.
2. Reasoning partial appears as ordered partial history and hands off after durable counterpart arrives.
3. Tool call without result stays as partial history and hands off to complete tool card after result arrives.
4. Input buffer appears as pending input queue, not partial history.
5. Detached browsing does not compose partial history into timeline and preserves only new activity indicator.

Automatable scope in this PR is covered by unit/type/static verification, and scenarios requiring live provider are linked to follow-up E2E evidence.
