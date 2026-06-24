---
title: "ADR-0053: Chat Session Resync Converges to History/Live State After Subscribe Ack"
created: 2026-06-09
tags: [architecture, frontend, chat]
---

# ADR-0053: Chat Session Resync Converges to History/Live State After Subscribe Ack

## Status

Accepted. This defines the new standard for Chat UI recovery when entering an active session or returning from inactive state.

## Background

Chat protocol separates persisted canonical event history and non-durable live state according to ADR-0047. However, synchronization order when entering screen, refreshing, or returning from tab/mobile app inactive state, and rendering modes by scroll state, were not defined as normalized states.

In particular, if REST history/live state is fetched before opening WebSocket subscription, live events between REST fetch and session subscription registration can be missed. Also, if a user is viewing middle history and returns after inactive state, rules are needed for whether latest live state should be composed below current history window, hidden, or reset to latest.

## Decisions

These decisions are referenced by stable IDs in implementation and SPEC.

- ADR-0053-D1: New entry/refresh fetches REST history/live after session subscribe ack.
- ADR-0053-D2: If user was at bottom before inactive, return to latest following state.
- ADR-0053-D3: If user was in middle scroll before inactive, return to detached history browsing state.
- ADR-0053-D4: Long-open visible screen performs subscription health check every 30 seconds before resync.
- ADR-0053-D5: Chat screen state is represented as latest following and detached history browsing ADT.

### 1. New entry/refresh fetches REST after session subscribe ack

When newly entering or refreshing an active session, client performs initial sync in this order:

1. Open WebSocket connection.
2. Send subscribe request for target session.
3. Wait for server's per-session `subscribed` ack.
4. Store WebSocket events arriving after ack in buffer until initial sync completes.
5. Fetch latest history by REST.
6. Fetch latest live state by REST.
7. Apply REST history and live state as screen baseline.
8. Replay buffered WebSocket events on top of baseline without duplicates.
9. Apply subsequent WebSocket events in real time.
10. Place screen at bottom.

`WebSocket open` is not subscription completion. Subscription completion means receiving server's per-session `subscribed` ack. Server must send ack only after registering that connection as delivery target for session events.

### 2. If at bottom before inactive, return to latest following state

If tab or mobile app returns from inactive to active, and scroll was at bottom immediately before entering inactive, client interprets this as intent to follow latest.

In this case, client performs the same sync order as new entry/refresh and moves to bottom. Live state rendering remains enabled. Live projections such as partial text, tool calling, zzz/thinking, and current run state continue rendering below latest history tail.

If user scrolls during sync, no separate transition rule is defined. If actual UX is awkward, improve with follow-up decision.

### 3. If in middle scroll before inactive, return to detached history browsing state

If tab or mobile app returns from inactive to active, and scroll was in middle immediately before entering inactive, client models this as detached history browsing state.

Detached history browsing is a normalized state for browsing a specific history window, not a state viewing the latest live tail. It is defined as an ADT variant, not exception code or temporary boolean.

Rules in detached history browsing:

1. History window has both older-direction cursor and newer-direction cursor.
2. Scrolling up fetches older history with older-direction cursor.
3. Scrolling down fetches newer history with newer-direction cursor.
4. Live state is not rendered in UI.
5. Partial text, tool calling, zzz/thinking, and latest live tail are not composed below current history window.
6. While live state is not rendered, show only “new messages” chip.
7. When user scrolls down to the latest durable history tail, resume live state rendering and transition to latest following state.
8. Clicking “new messages” chip discards current detached history window and performs latest reset.

Latest reset works similarly to refresh/new entry. Client refetches REST history at bottom, refetches REST live state, reenables live state rendering, and moves screen to bottom.

### 4. Long-open visible screen health-checks every 30 seconds then resyncs

If screen remains visible for a long time, resync every 30 seconds regardless of current running state. Local state that appears idle can itself be stale, so do not resync only when running/live state exists.

Periodic resync starts with session subscription health check, not WebSocket reconnect. Health check ack is not a simple socket ping/pong; it is a barrier confirming that the connection is delivery target for the target session.

Visible periodic reconcile follows this order:

1. Client sends subscription health check for current session.
2. Server verifies the connection is a delivery target for session events.
3. Server sends health check ack.
4. WebSocket events arriving after ack are stored in buffer until reconcile completes.
5. Fetch latest history by REST.
6. Fetch latest live state by REST.
7. Apply REST history and live state according to current ADT state.
8. Replay buffered WebSocket events on top of baseline without duplicates.
9. Apply subsequent WebSocket events in real time again.

If health check ack is not received, do not trust connection or subscription. Switch to reconnect or resubscribe recovery flow, then fetch REST history/live state after receiving subscribe ack.

In latest following state, apply periodic reconcile result to latest screen and keep live state rendering plus bottom follow. In detached history browsing state, even if periodic reconcile runs, do not render live state on screen; keep only “new messages” chip. Do not force current history window to latest tail.

### 5. Chat screen state is represented as ADT

Chat screen has at least these two normalized states.

#### Latest following

State rendering latest durable history tail and live state together.

- Viewing latest history tail.
- Live state rendering is enabled.
- Renders partial text, tool calling, zzz/thinking, and current run state.
- Applies new WebSocket events to latest tail.
- Can perform bottom follow behavior.

#### Detached history browsing

State browsing a middle history window.

- Not viewing latest live tail.
- History window has older-direction cursor and newer-direction cursor.
- Live state rendering is disabled.
- Shows “new messages” chip.
- Transitions to latest following only after reaching latest durable history tail or performing latest reset.

## Rejected Directions

### REST fetch then WebSocket subscribe

Rejected. Events occurring between REST fetch and session subscription registration can be missed.

### Treat WebSocket open as subscription completion

Rejected. Connection open does not guarantee registration as delivery target for a specific session.

### Compose live state below history window in middle scroll state

Rejected. The user is viewing a middle history window, not latest tail. Composing live projections such as partial text or tool calling would create a screen that skips an unloaded newer-direction history gap.

### Handle middle scroll return as exception flag

Rejected. Middle history browsing is a normal Chat screen state, not a recovery edge case. Define it as ADT variant so pagination, live state rendering, and latest reset transitions are explicit.

## Consequences

### Expected Benefits

- Removes event gap between REST and WebSocket on new entry/refresh.
- Clearly separates latest-following state and middle-history-browsing state on inactive return.
- Avoids mixing history gap and live tail by not forcibly composing live state during middle scroll return.
- Newer-direction cursor lets users naturally scroll down from middle history window to latest durable tail.
- “New messages” chip is defined as latest reset entry point, not a simple scroll movement.

### Cost and Risks

- WebSocket protocol must implement precise per-session subscribe ack semantics.
- History API must support newer-direction pagination cursor as well as older-direction cursor.
- Frontend state must model latest following and detached history browsing as ADT.
- It must reliably detect reaching latest durable tail in detached history browsing state.

## Open Questions

None. If implementation reveals awkward UX in detailed transitions, handle them through follow-up ADR or SPEC update.

## Related Documents

- [ADR-0047: Chat protocol uses canonical event history/live API](./0047-chat-protocol-history-live-state.md)
- [ADR-0050: Live/history projection handoff and stream batching are handled at canonical event level](./0050-live-history-projection-handoff-and-stream-batching.md)
