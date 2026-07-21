---
title: "Chat Session Resync and Scroll State Design"
created: 2026-06-09
updated: 2026-06-09
tags: [architecture, frontend, backend, chat]
document_role: supporting
document_type: supporting-consolidation
migration_source: "docs/azents/design/chat-session-resync-scroll-state.md"
supporting_role: consolidation
---

# Chat Session Resync and Scroll State Design

## Overview

Chat screen reads persisted canonical history and non-durable live state separately. This design defines rendering modes for new session entry, refresh, reconnect, periodic reconcile while visible, and scroll position when returning from inactive state.

Base decision is [chat-260609/ADR](../adr/chat-260609-chat-resync-scroll.md). Implementation uses only the new protocol without compatibility fallback. WebSocket open itself does not mean session event delivery registration is complete; client uses `subscribed` ack or `subscription_health_check_ack` as barrier before applying REST history/live baseline.

## Goals

- Remove event gap between REST fetch and WebSocket session subscription.
- Split Chat screen state into latest following and detached history browsing ADT.
- In detached state, do not compose live state below history window.
- History API provides both older-direction and newer-direction cursors.
- Long-open visible screen converges through subscription health check and REST baseline, not reconnect.

## Non-goals

- Introduce virtualized transcript layout.
- Keep existing legacy WS delta protocol.
- Restore existing `/messages` aggregate endpoint.
- Pass session concept to upload API.

## Requirements

| ID | Content | Base decision |
| --- | --- | --- |
| REQ-1 | Existing session WebSocket sends `subscribed` ack after session delivery registration. | [chat-260609/ADR-D1](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-2 | Initial history/live REST fetch happens only after `subscribed` ack. | [chat-260609/ADR-D1](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-3 | WS events received while applying baseline are stored in buffer and replayed after baseline apply. | [chat-260609/ADR-D1](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-4 | `GET /history` supports `before` and `after` cursors. | [chat-260609/ADR-D3](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-5 | Sending `before` and `after` together is rejected with 400. | [chat-260609/ADR-D3](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-6 | Chat timeline state is represented as `LATEST_FOLLOWING` and `DETACHED_HISTORY_BROWSING` ADT. | [chat-260609/ADR-D5](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-7 | Detached state does not render live state, pending input buffer, or model/run indicator. | [chat-260609/ADR-D3](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-8 | Clicking “new messages” chip in detached state performs latest reset. | [chat-260609/ADR-D3](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-9 | While visible, re-fetch REST baseline every 30 seconds after subscription health check ack. | [chat-260609/ADR-D4](../adr/chat-260609-chat-resync-scroll.md) |
| REQ-10 | If health check ack fails, do not trust session subscription and switch to ticket refresh/reconnect path. | [chat-260609/ADR-D4](../adr/chat-260609-chat-resync-scroll.md) |

## Decision Table

| Decision | Implementation requirements |
| --- | --- |
| [chat-260609/ADR-D1](../adr/chat-260609-chat-resync-scroll.md) | REQ-1, REQ-2, REQ-3 |
| [chat-260609/ADR-D2](../adr/chat-260609-chat-resync-scroll.md) | REQ-2, REQ-3, REQ-8, REQ-9 |
| [chat-260609/ADR-D3](../adr/chat-260609-chat-resync-scroll.md) | REQ-4, REQ-5, REQ-6, REQ-7, REQ-8 |
| [chat-260609/ADR-D4](../adr/chat-260609-chat-resync-scroll.md) | REQ-3, REQ-9, REQ-10 |
| [chat-260609/ADR-D5](../adr/chat-260609-chat-resync-scroll.md) | REQ-6, REQ-7, REQ-8 |

## WebSocket Protocol

Server registers Redis broadcast subscription after authentication and access control pass on `/chat/v1/sessions/{session_id}` connection. After registration completes, it sends this ack.

- `type`: `subscribed`
- `session_id`: current session id

Client does not use that connection as latest baseline source before receiving `subscribed`.

Periodic reconcile starts with this client control message.

- `type`: `subscription_health_check`
- `session_id`: current session id
- `request_id`: client-generated id

Server sends ack confirming the same WebSocket connection is a session delivery target.

- `type`: `subscription_health_check_ack`
- `session_id`: current session id
- `request_id`: request id

If ack timeout or close occurs, client switches to ticket refresh/reconnect path.

## REST History API

`GET /chat/v1/sessions/{session_id}/history` supports these query params.

- `limit`: 1~100
- `before`: persisted event page older than this event id
- `after`: persisted event page newer than this event id

`before` and `after` cannot be used together.

Response returns canonical event page and cursor metadata.

- `items`: canonical events sorted from oldest to newest
- `has_more`: whether older event exists
- `has_newer`: whether newer event exists
- `next_cursor`: next older page cursor
- `previous_cursor`: next newer page cursor

## Frontend State

Chat timeline state has this ADT:

- `LATEST_FOLLOWING`: renders latest durable history tail together with live state.
- `DETACHED_HISTORY_BROWSING`: browses a specific history window and does not render live state.

`useChatWebSocket` handles WebSocket connection, ack barrier, event buffer, and health check. `useChatSessionContainer` handles REST baseline application and timeline ADT transitions. `ChatView` passes scroll position and chip interaction to container.

## Synchronization Flow

### Initial entry

1. Open WebSocket connection.
2. Wait for `subscribed` ack.
3. Store WS events arriving after ack in buffer.
4. Fetch REST `/history`, `/live`.
5. Apply baseline.
6. Replay buffered WS events.
7. Transition to `LATEST_FOLLOWING`.

### Detached transition

When user moves away from latest tail and browses history, transition to `DETACHED_HISTORY_BROWSING`.

- Subsequent WS events are stored in buffer instead of rendered immediately.
- Current live message and pending input buffer are removed from screen.
- Show “new messages” chip.

### Return to latest

Perform latest reset when one of these occurs:

- Click “new messages” chip.
- Reach latest durable tail through newer-direction cursor.

Latest reset re-reads REST `/history`, `/live`, enables live state rendering, and transitions to `LATEST_FOLLOWING`.

## Implementation Targets

### Backend

- `azents.transport.chat`: add subscription ack and health check ack transport dump.
- `api/public/chat/v1`: split WebSocket send loop and receive loop, protect concurrent sends with `asyncio.Lock`.
- `MessageRepository`: add newer-direction pagination based on `after` cursor.
- `ChatSessionService`: pass `after` cursor and `has_newer` to history list.
- Regenerate OpenAPI public spec.

### Frontend

- `useChatWebSocket`: add `subscribed` ack barrier, health check promise, WS event buffer.
- `useChatSessionContainer`: add timeline ADT, latest reset, detached transition, recent cursor load.
- `ChatView`: show detached state chip, latest reset click, hide pending/live indicator.
- Update tRPC chat router and generated public client query shape.

## Verification Plan

- Python ruff: chat API/service/repo/transport targets.
- Python pyright: chat API/service/repo/transport targets.
- Python pytest: chat service live/input buffer targeted tests.
- TypeScript typecheck: `@azents/web`.
- Include OpenAPI/client regeneration result.
- Document index check.

## Risks and Mitigations

- WebSocket implementation can break if WS and receive loops send concurrently. Server serializes sends with `asyncio.Lock`.
- Buffered events can accumulate while detached for long time. Currently replay on latest reset or reaching latest tail. Long detached memory pressure is handled in follow-up virtualization/history window management.
- If newer-direction cursor incorrectly judges latest tail reached, live state return can be delayed. Use page with `has_newer=false` as latest reset trigger.
