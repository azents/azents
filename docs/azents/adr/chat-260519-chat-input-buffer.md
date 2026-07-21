---
title: "Split Chat Input Buffer into Separate RDB Table"
created: 2026-05-19
tags: [architecture, backend, frontend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: chat-260519
historical_reconstruction: true
migration_source: "docs/azents/adr/0034-chat-input-buffer.md"
---

# chat-260519/ADR: Split Chat Input Buffer into Separate RDB Table

## Context

nointern chat allows users to send additional messages while a run is active. Currently, the first input and normal inputs are stored as `UserInputEvent` before engine execution, but additional input during a run stays only in `_SessionRunner._queue` and is promoted to `events` only when `poll_messages()` is called. Therefore, if refresh, worker restart, or process termination happens between message receipt and model turn injection, there is a persistence gap where the user-sent message is not visible in durable history.

Solving this gap by mixing queued state into `events` would blur the meaning of the append-only event log. `events` is already used as the durable source for model history and UI history, and `external_id` dedup plus run boundary/truncate rules all assume items that are already finalized as model turns or system events.

A buffered message is input that has not yet been injected into the model. In UI, it is more natural to show it in a separate pending area at the bottom of the current conversation rather than inserting it into the middle of the past event timeline. This avoids making ordering between buffer row creation time and event id a UI requirement.

## Decision

Store chat input buffer in a separate RDB table, `input_buffers`, independent from `events`.

- `input_buffers` is the source of truth for "user input accepted by the server but not yet injected into a model turn."
- WebSocket message receive path always stores user input in `input_buffers` first, regardless of run state. First message and idle-state message are not exceptions.
- Every model-call turn flushes `input_buffers` at start. The first turn uses the same path; engine/worker reads pending buffer rows and promotes them to `UserInputEvent`.
- Promoted `UserInputEvent.external_id` uses the original buffer row id. If retry or recovery tries to promote the same buffer again, `events(session_id, external_id)` dedup prevents duplicate events.
- Promotion must append `events` and remove buffer rows inside the same DB transaction.
- UI receives event history and input buffer as separate collections and renders them separately. Buffer rows are always displayed at the bottom of the chat, independent of event id/time ordering.
- Users may delete buffer rows that have not yet been promoted without confirmation.
- Do not add queued/pending pseudo-events to `events`.

## Considered Options

### Option A — Immediately store in `events.user_input` during run

The advantage is that no new table is needed and REST history only reads the existing event list. However, input not yet injected into the model becomes mixed into event history. Model turn history ordering, truncate boundary, durable echo dedup, and SDK user echo skip rules can no longer distinguish "injection completed" from "only accepted." This especially conflicts with the UX of always rendering buffer at the bottom versus event-id-based history ordering.

### Option B — Treat Redis / `_SessionRunner._queue` as durable source

Implementation change is small, but it does not solve the core pre-poll persistence gap. A message the user saw as accepted can disappear after process termination, Redis loss, or REST history reload after WebSocket reconnect.

### Option C — Recover pending bubble through client localStorage

This helps a single browser refresh, but the source of truth for server-accepted input differs by client. Server state and UI state diverge across other devices, session delete, stuck recovery, and E2E verification.

### Option D — Use separate RDB input buffer

This makes server acceptance durable while preserving the meaning of `events`. It also matches the existing engine boundary of promotion immediately before model call, and UI can display buffer in a bottom pending area. It adds a table and API/WS payload, but gives the clearest state separation.

## Consequences

### Positive

- Removes crash/restart gap between message receipt and model-call boundary.
- Preserves `events` as an event log finalized into model history.
- Buffered messages always render at the bottom, so event ordering correction logic is unnecessary.
- Uses buffer id as `UserInputEvent.external_id` to prevent duplicate promotion retry.
- REST history reload and WebSocket live UI share the same server-side pending state.

### Negative / Trade-offs

- Adds `input_buffers` table, repository/service, REST/WS response shape, and frontend state.
- API contract expands because event history and buffer list must be read and rendered together.
- Locking/ordering rules for model-call boundary promotion transaction must remain clear.

### Follow-up Constraints

- This decision creates the constraint that queued state must not be mixed into `events`. Even if future UI further refines "pending" display, the source must be `input_buffers`.
- Since buffer rows are treated as bottom-rendered items, buffer row id/created_at are used only for ordering inside the pending area, not for event timeline ordering.

## Migration provenance

- Historical source filename: `0034-chat-input-buffer.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
