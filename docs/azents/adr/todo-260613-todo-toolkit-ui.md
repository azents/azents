---
title: "Expose Session Todo State through Toolkit State and Chat Live State"
created: 2026-06-13
tags: [architecture, backend, frontend, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: todo-260613
historical_reconstruction: true
migration_source: "docs/azents/adr/0058-session-todo-toolkit-state-ui.md"
---

## Status

Accepted

## Context

Azents chat needs UI that lets users see at a glance the current task list the agent is working on. This is especially important for sessions that perform multi-step work, such as long-running coding agents, research agents, and operations agents.

Existing system has `toolkit_states` table and `ToolkitStateStore` abstraction for storing session-scoped durable JSON state. Chat screen also separates durable history and current live state, updating current UI state through REST write snapshot and WebSocket event.

Constraints for this decision:

- Do not create new compaction changes.
- Do not create a new todo-specific table.
- Use existing Toolkit State as storage.
- UI shows one-line preview above input box.
- Clicking preview opens full todo list in Modal.
- First UI pass does not provide user editing.
- Todo status uses only `pending`, `in_progress`, `completed`.
- Preview selection order is `in_progress` first, then `pending`; within same status, preserve list order.

## Decision

Session Todo is stored as session-scope state in `toolkit_states`. Identity uses builtin toolkit namespace and `todo` state name.

Stored payload is schema version 1 todo list, and each item has `id`, `content`, and `status`. Allowed status values are only `pending`, `in_progress`, and `completed`.

Agent updates todo list through builtin tool `update_todo`. This tool provides `replace`, `upsert`, `remove`, and `clear` operations. Direct user editing UI is not included in this decision.

Chat live state response includes `todo` snapshot. Frontend does not call a separate todo read API; it receives todo state through existing `/chat/v1/sessions/{session_id}/live`, REST write snapshot, and WebSocket `todo_state_changed` event using the same live state reducer.

UI shows a rounded peek bar immediately above chat input box. If there is no item to show, hide the bar. The bar is one-line truncated, and clicking it opens a read-only Modal showing the full todo list.

Compaction prompt, compaction event, and durable transcript schema do not change. Todo is side state of current session and is not injected into transcript summary policy.

## Consequences

Pros:

- Reuses existing Toolkit State session-scoped durable state model without a new table.
- REST live snapshot and WebSocket live event converge through the same UI state reducer.
- Todo does not mix into transcript, avoiding conversation body pollution.
- Existing context compaction behavior is minimally affected because compaction policy does not change.

Costs and risks:

- Todo is session side state, so external consumers restoring only transcript do not see todo.
- If agent does not call `update_todo`, UI remains empty.
- Users cannot edit directly for now, so incorrect todo is corrected only by next agent tool call.

## Rejected Alternatives

### Add new todo table

Rejected. Todo is session-scoped durable JSON state and does not need a separate query model or relational constraints. A new table increases migration and repository/API surface while duplicating the purpose of existing Toolkit State.

### Insert todo message into chat transcript

Rejected. Todo is current work state, not conversation utterance. Inserting it into transcript creates unnecessary branches in compaction, history pagination, and adapter rendering.

### Add todo tab to right Workspace panel

Rejected. Right panel is runtime workspace area for workspace/projects/settings. Todo is current task state closest to the user's next input, so preview above input box is more appropriate.

### Add separate todo read API

Rejected. Chat UI already subscribes to live state snapshot. A separate API would split state source. This decision makes UI read todo from existing live state projection.

## Migration provenance

- Historical source filename: `0058-session-todo-toolkit-state-ui.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
