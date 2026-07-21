---
title: "Define Chat Live/History Handoff and Streaming Partial Batching"
created: 2026-06-04
tags: [architecture, backend, frontend, chat, streaming, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: live-260604
historical_reconstruction: true
migration_source: "docs/azents/adr/0050-live-history-projection-handoff-and-stream-batching.md"
---

# live-260604/ADR: Define Chat Live/History Handoff and Streaming Partial Batching

## Status

Accepted.

[chat-260604/ADR](./chat-260604-chat-protocol-history-live.md)'s canonical history/live protocol decision remains in effect. This ADR is a follow-up decision that fixes handoff defects and streaming partial storage/delivery bottlenecks found after implementation.

## Background

Chat protocol separated durable history and non-durable live projection using canonical event transport. However, actual UI behavior showed these issues:

- Live state updates through Redis and WebSocket, but history reflection appears not to merge into the screen in real time.
- Tool call appears as live projection while running, then disappears from UI when durable event is appended and live counterpart is removed. Refreshing shows it again from REST history.
- Text streaming partials occur very frequently, causing Redis read/write/expire and WebSocket broadcast for every delta. This path can become a bottleneck.

Code review showed that frontend reducer early-returns on some tool call events when receiving `history_event_appended`, instead of applying them to history state. Backend removes live counterpart after appending durable event, so from the client selector perspective only live event disappears and history event appears absent.

Also, backend live projection store accumulates projection in Redis and sends WebSocket on every `ContentDelta` / `ReasoningDelta`. When streaming provider emits small deltas quickly, live projection update frequency equals provider token cadence.

## Decision

### 1. Define handoff invariant

When a durable canonical event is appended, client must apply it to history state first. Then it handles removal of matching live projection.

Transport action processing rules:

1. `history_event_appended` upserts every renderable canonical event into history list.
2. `live_event_upserted` upserts into live list.
3. `live_event_removed` removes only from live list.
4. Selector prioritizes history when the same semantic entity exists in both history and live.

Frontend reducer must not skip renderable event application merely because it is `isHistoryEvent`. Tool call is a renderable canonical event in durable history too.

### 2. Backend guarantees order: history append before live remove

WebSocket publish order follows this principle:

1. Publish durable canonical event append action.
2. Publish matching live projection remove action.

Within the same Redis Pub/Sub channel, preserve publish order by sequentially awaiting in one write path. This reduces flicker or disappearance caused by observing live remove first.

### 3. Server-side batching for streaming partials

`ContentDelta` and `ReasoningDelta` are not reflected to Redis live store and WebSocket at provider delta cadence. A worker/session-level partial batcher combines deltas and flushes based on short time window or minimum character amount.

Start with operationally tunable constants:

- maximum delay: around 50-100ms
- maximum accumulated characters: small enough for provider/UX requirements
- always flush before run end, turn end, or durable assistant/reasoning event append

### 4. Apply separate policy for function call argument partials

Tool/function call argument delta can become meaningful only after a later boundary than text. Initial implementation prioritizes text/reasoning batching, and function call delta follows one of these policies:

- Apply the same short debounce batching as text.
- Or keep existing immediate update while first fixing live/history handoff bug.

The core reason tool call disappears from UI is handoff, not batching. Tool call lifecycle consistency is solved by the handoff invariant.

### 5. Redis stores latest live projection, not finalized history

Batching does not mean storing every delta in Redis. Redis continues to store only latest live projection. Durable transcript stores only finalized canonical events.

## Rejected Directions

### Store all streaming partials in canonical events table

Rejected. Partials are not finalized transcript. Making events table a token-cadence write path increases durable history cost and noise.

### Apply only client-side batching

Rejected. WebSocket payload frequency and Redis write bottleneck already happen server-side. Client-side throttling only reduces browser render cost and does not solve backend bottleneck.

### Delay live projection removal until run end

Rejected. Once persisted history exists, the matching live counterpart should be removed so reload/reconnect and live API remain simple. Delayed removal keeps duplication/priority problems longer.

### Ignore tool history events in UI

Rejected. Tool call/result is part of durable canonical history and should be visible after refresh. It must render with the same view model even after live projection is removed.

## Consequences

### Expected Benefits

- Tool call running state no longer disappears at durable append and reappears after refresh.
- Redis write and WebSocket broadcast frequency decreases during text/reasoning streaming.
- Live state and history state roles are clarified through reducer/selector invariants.
- Durable history append appears in UI immediately without reload/reconnect.

### Cost and Risks

- Partial batching must avoid missing the final delta flush.
- Flush timer must correctly handle session/run lifecycle and cancellation.
- Too large batch window can make typing feel sluggish.
- Too small batch window provides little bottleneck relief.

## Related Documents

- [chat-260604/ADR: Chat protocol uses canonical event history/live API](./chat-260604-chat-protocol-history-live.md)
- [Chat live/history handoff and streaming partial batching design](../design/live-history-projection-and-partial-batching.md)

## Migration provenance

- Historical source filename: `0050-live-history-projection-handoff-and-stream-batching.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
