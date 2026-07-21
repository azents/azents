---
title: "Message Queueing — User Message Injection During Run Historical Requirements Reconstruction"
created: 2026-03-05
implemented: 2026-03-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: message-260305
historical_reconstruction: true
migration_source: "docs/azents/design/message-queueing.md"
---

# Message Queueing — User Message Injection During Run Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `message-260305`
- Source: `docs/azents/design/message-260305-message-queueing.md`
- Historical source date basis: `2026-03-05`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Currently agent session does not process next message until `engine.run()` completes (RunComplete). FE also enables input only after receiving RunComplete.

Improve this by creating structure where user message sent while run loop is running is **injected into next LLM turn**.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

1. **Basic flow**: send message 1 → during tool execution send message 2 → message 2 reflected in next turn
2. **Multiple messages**: send messages 2, 3, 4 during tool execution → all injected at once
3. **Command blocking**: send `/compact` during run → ignored (FE block + backend defense)
4. **No message**: no additional message during tool execution → existing behavior unchanged
5. **Error recovery**: engine errors during tool execution → unpolled messages remain in queue and are processed in next run

## Supporting Scenarios

1. **Basic flow**: send message 1 → during tool execution send message 2 → message 2 reflected in next turn
2. **Multiple messages**: send messages 2, 3, 4 during tool execution → all injected at once
3. **Command blocking**: send `/compact` during run → ignored (FE block + backend defense)
4. **No message**: no additional message during tool execution → existing behavior unchanged
5. **Error recovery**: engine errors during tool execution → unpolled messages remain in queue and are processed in next run

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
