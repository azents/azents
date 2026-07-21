---
title: "Expose Session Todo State through Toolkit State and Chat Live State Historical Requirements Reconstruction"
created: 2026-06-13
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: todo-260613
historical_reconstruction: true
migration_source: "docs/azents/adr/0058-session-todo-toolkit-state-ui.md"
---

# Expose Session Todo State through Toolkit State and Chat Live State Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `todo-260613`
- Source: `docs/azents/adr/todo-260613-todo-toolkit-ui.md`
- Historical source date basis: `2026-06-13`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

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

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
