---
title: "Session Todo UI Design"
created: 2026-06-13
updated: 2026-06-13
tags: [backend, frontend, engine, historical-reconstruction]
document_role: primary
document_type: design
snapshot_id: todo-260613
migration_source: "docs/azents/design/session-todo-ui.md"
historical_reconstruction: true
---

## Background

In long-running work, Azents chat makes it hard for users to immediately understand what is currently in progress. Existing timeline shows durable transcript and partial live projection, but the work plan itself is buried in assistant text or disappears in the next turn.

This design shows session todo maintained by agent in a small area above chat input, and lets users click it to view the full list.

## Goals

- Agent maintains current work plan as session-scoped durable state.
- User sees one-line current todo preview immediately above chat input.
- Preview is shown in one line only, truncating overflow text.
- Clicking preview opens Modal with full todo list.
- Hide UI if there is no todo.
- First implementation does not provide direct user editing.

## Non-goals

- Create new todo-specific table
- New compaction policy or compaction prompt change
- Store todo as durable chat transcript event
- User todo editing UI
- Separate todo read API

## Storage Model

Todo is stored in existing `toolkit_states` table.

- scope: `session`
- toolkit namespace: `todo`
- state name: `todo`
- schema version: `1`
- payload: `items` array

Each item has these fields:

- `content`: todo text visible to user
- `status`: `pending`, `in_progress`, `completed`

Do not add new status values. UI and prompt both handle only the same three values.

## Tool Design

Add TodoToolkit as always-on toolkit not exposed to user Toolkit config, similar to shell/builtin, and expose `update_todo` tool without prefix.

Operation:

- `replace`: replace entire list
- `clear`: clear all

After tool call, server publishes stored snapshot as `todo_state_changed` WebSocket event. This event is live UI control state, not durable transcript.

## Live State Design

Add `todo` field to Chat live snapshot.

- Include in `/chat/v1/sessions/{session_id}/live` response.
- Include in REST write response snapshot.
- WebSocket updates immediately with `todo_state_changed`.

Frontend manages todo in existing chat live reducer without separate read API.

## UI Design

### Location

Todo preview is shown immediately above chat input area. It is not inserted as message bubble in transcript, and not placed in right Workspace panel.

### Preview bar

- Show as one-line checklist strip attached immediately above input box. Only top corners are rounded, bottom appears connected to input area.
- Prefer showing `in_progress` item.
- If no `in_progress`, show first `pending` item.
- Within same status, preserve todo list order.
- Hide preview if only `completed` items remain.
- Truncate text to one line.
- Show completed count and total count on the right.

### Modal

Clicking preview bar opens Modal.

- Show full todo list in order.
- Each item shows status badge and content.
- Read-only.

## Implementation Scope

Backend:

- Add Toolkit State model, state store, and `update_todo` tool in `engine/tools/todo.py`.
- Add todo to TodoToolkit prompt and tool catalog.
- Add `TodoStateChanged` engine event.
- Add todo to Chat live snapshot response.

Frontend:

- Add todo snapshot/event to chat type.
- Add todo to live reducer in `useChatSessionContainer`.
- Add `TodoPreviewBar` component and Storybook story.
- Place preview bar above input area in `ChatView`.

Docs:

- Write [todo-260613/ADR](../adr/todo-260613-todo-toolkit-ui.md).
- Write this design.
- Write or update chat live state / toolkit state spec.

## Test Strategy

### E2E Primary Verification Matrix

- When agent creates `in_progress` todo with `update_todo`, preview appears above input.
- If no `in_progress` exists but `pending` exists, first pending item is shown.
- If todo is absent or only completed items exist, preview is not shown.
- Clicking preview opens Modal and shows full list.
- Todo from live snapshot remains after REST write.
- Preview updates immediately when WebSocket `todo_state_changed` is received.

### Local/CI Verification

- Python: `uv run ruff check --fix .`, `uv run ruff format .`, `uv run pyright`, related pytest
- TypeScript: `pnpm run generate`, `pnpm run format`, `pnpm run lint`, `pnpm run typecheck`
- Storybook: manually/CI check empty, pending-only, in-progress states of `TodoPreviewBar`

### Fixture and Seed

Do not add separate database seed in first PR. If E2E needs it, inject `todo_state_changed` event through test route or mocked WebSocket event.

### Evidence

Leave the following evidence in PR:

- OpenAPI/client generation result
- Python quality check result
- TypeScript quality check result
- Storybook or screenshot evidence if possible

## Follow-ups

- Validate whether direct user editing UI is needed.
- Use user feedback to confirm whether hiding completed-only list from preview is sufficient.
- Handle relationship between subagent todo and parent todo in a separate ADR if needed.
