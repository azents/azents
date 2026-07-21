---
title: "Split Chat Input Buffer into Separate RDB Table Historical Requirements Reconstruction"
created: 2026-05-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: chat-260519
historical_reconstruction: true
migration_source: "docs/azents/adr/0034-chat-input-buffer.md"
---

# Split Chat Input Buffer into Separate RDB Table Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `chat-260519`
- Source: `docs/azents/adr/chat-260519-chat-input-buffer.md`
- Historical source date basis: `2026-05-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

nointern chat allows users to send additional messages while a run is active. Currently, the first input and normal inputs are stored as `UserInputEvent` before engine execution, but additional input during a run stays only in `_SessionRunner._queue` and is promoted to `events` only when `poll_messages()` is called. Therefore, if refresh, worker restart, or process termination happens between message receipt and model turn injection, there is a persistence gap where the user-sent message is not visible in durable history.

Solving this gap by mixing queued state into `events` would blur the meaning of the append-only event log. `events` is already used as the durable source for model history and UI history, and `external_id` dedup plus run boundary/truncate rules all assume items that are already finalized as model turns or system events.

A buffered message is input that has not yet been injected into the model. In UI, it is more natural to show it in a separate pending area at the bottom of the current conversation rather than inserting it into the middle of the past event timeline. This avoids making ordering between buffer row creation time and event id a UI requirement.

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

- This decision creates the constraint that queued state must not be mixed into `events`. Even if future UI further refines "pending" display, the source must be `input_buffers`.
- Since buffer rows are treated as bottom-rendered items, buffer row id/created_at are used only for ordering inside the pending area, not for event timeline ordering.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
