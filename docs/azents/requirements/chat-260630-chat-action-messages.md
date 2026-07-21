---
title: "Chat Action Messages Historical Requirements Reconstruction"
created: 2026-06-30
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: chat-260630
historical_reconstruction: true
migration_source: "docs/azents/adr/0086-chat-action-messages.md"
---

# Chat Action Messages Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `chat-260630`
- Source: `docs/azents/adr/chat-260630-chat-action-messages.md`
- Historical source date basis: `2026-06-30`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently has multiple chat-input control paths that look similar to the user but are implemented as separate mechanisms:

- Normal user messages are sent through the chat message write path and become input-buffer work for the normal run loop.
- Slash commands are discovered through `GET /chat/v1/commands`, displayed by `ChatInput` as a simple `/name` autocomplete list, and sent through `POST /chat/v1/sessions/{session_id}/commands`.
- The only registered command is currently `compact`; it is stored as a pending session command and processed before buffered user messages.
- Session Goal state is visible near the input through `TodoPreviewBar` and supports edit, delete, pause, and resume for an existing Goal.
- There is no user-facing UI for directly creating a Goal. Goal creation is currently exposed to the agent through the Goal toolkit (`create_goal`) rather than as a first-class chat input action.

This makes the current slash-command UI too narrow for upcoming input actions. Future input affordances need to support not only execute-and-finish commands such as compaction, but also Goal creation and later Skill invocation that should participate in the normal run loop.

The chat input needs a standard payload shape that can represent these actions without turning every feature into another bespoke input branch.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

The chat service exposes REST methods to update or clear an existing Goal and to pause or resume an existing Goal. The current update path intentionally does not create a Goal when no Goal exists. Existing Goal management is covered by the Goal preview/detail UI.

Goal creation needs a user-facing action path, but existing Goal edit/delete/pause/resume should remain in the existing Goal UI instead of becoming additional action types.

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
