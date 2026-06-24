---
title: "ADR-0051: Chat Writes Use REST Commit Boundary"
created: 2026-06-05
tags: [architecture, backend, frontend, api, chat]
---

# ADR-0051: Chat Writes Use REST Commit Boundary

## Status

Accepted.

In Web chat, message sending relied on WebSocket write path, repeatedly causing UI and server to disagree about whether a message was accepted depending on browser/mobile network/reconnect timing. Attachment messages were especially prone to appearing as duplicates because frontend optimistic pending bubble and server input buffer live projection used different attachment representations.

## Background

Current Chat UI uses WebSocket for both reads and writes. Client sends messages through WebSocket and creates optimistic pending bubble before server ack. Server later sends input buffer or live event projection again through WebSocket, and frontend must match optimistic state with server state based on payload.

This structure creates these problems:

- WebSocket connection state becomes write availability state, so input can appear lost around mobile background/reconnect boundaries.
- UI renders pending bubble before confirming that user input was committed to DB.
- Attachment input can break payload dedupe because upload-time `exchange://...` URI differs from post-user-input-materialization `model-file:...` representation.
- New session `/sessions/new` WebSocket first message can have an exception path that bypasses input buffer and sends directly to broker in existing implementation.
- If message/edit/command remain as WebSocket writes, write responsibility remains mixed into WebSocket handler independently of history/live canonical event protocol.

ADR-0034 decided input buffer is the source of truth for user input accepted by the server. ADR-0047 aligned chat screen history/live read contract around canonical events. This ADR moves user input write boundary to REST commit boundary according to the same principles.

## Decisions

### ADR-0051-D1. Move message/edit/command writes to REST

Web chat normal messages, user message edits, and slash command writes are handled through REST endpoints instead of WebSocket.

In first scope, stop request remains on WebSocket. Stop is a latency-sensitive control signal that interrupts an active run, and REST stop migration remains a follow-up goal.

### ADR-0051-D2. REST write success means input buffer commit

Message write success response is returned only after user input is committed as an input buffer DB row. API sends input signal to worker after commit. However, signal delivery itself is not atomic with the API transaction.

Input buffer is the source of truth, and worker owns signal loss/duplication detection and recovery. API does not treat broker/wake-up delivery success as a condition for user message persistence success.

### ADR-0051-D3. REST write response returns authoritative live snapshot

REST write response does not return only one accepted item. It returns the authoritative chat live snapshot after server commit.

Snapshot includes current live state needed to restore screen, such as session id, pending input buffer live projections, live events, run state, and history reload hint. It does not include the full durable history page by default. For operations requiring durable history reload, such as edit/command, return an explicit hint such as `history_reload_required`.

### ADR-0051-D4. All REST writes are idempotent by `client_request_id`

Message/edit/command REST requests require `client_request_id`. Retrying with the same user/runtime/request id does not create a new input buffer or new command/edit operation; it returns the current authoritative live snapshot.

This idempotency key prevents the same user intent from being stored as multiple input buffers after network timeout retry, browser foreground return, or duplicate submit.

### ADR-0051-D5. New session write uses REST message contract without session id

The first message of a new session uses a separate REST endpoint with the same semantics as existing session message REST, but request does not receive session id. Server creates the session, then creates input buffer through the same buffer-first path and returns snapshot.

Remove the `/sessions/new` WebSocket write path that receives first message and creates session. First message of a new session also does not bypass input buffer.

### ADR-0051-D6. Remove frontend timeline optimistic pending bubble

Frontend does not create optimistic pending bubble in timeline immediately after message REST request. While request is in progress, show sending state only at composer/send button level.

Render pending input buffer bubble only after receiving REST response snapshot. Therefore, timeline shows only server-committed input buffer/live state.

### ADR-0051-D7. Serialize REST writes per session in first scope

Frontend does not send multiple message/edit/command REST writes concurrently in the same session. If one write is in-flight, block another write submit.

Additional user input during a run remains allowed, but write requests themselves are processed one at a time. Snapshot-revision-based concurrent write ordering is left as a future extension.

### ADR-0051-D8. Remove WebSocket message/edit/command write path with REST migration

After REST migration, WebSocket is responsible only for live subscription and first-scope stop control. Backend WebSocket handler does not process message, edit_user_message, or command write payloads.

Do not provide runtime fallback to existing WebSocket write when REST write breaks. Use deployment rollback if needed.

### ADR-0051-D9. Run possible verification paths and track hard E2E as GitHub Issues

API E2E and browser E2E are primary QA targets for this change. Items hard to execute due to current agent runtime or CI/testenv constraints must not be disguised as PASS.

Run verifications that are possible directly. For blocked verifications, create GitHub Issues for follow-up. Issue records scenario intended to verify, why it cannot run, required runner/fixture/credential, expected result, and related PR/document links.

## Rejected Directions

### Keep WebSocket write and switch only frontend to REST

Rejected. Two write paths remain for the same feature, and exception paths such as new session WebSocket first message remain. The expectation that runtime can instantly fallback to WebSocket write when REST fails also does not hold in real deployment environments.

### Return only one accepted input buffer in REST response

Rejected. Frontend would need to merge local state and server state again, and this is insufficient for writes such as command/edit that cannot be described by one accepted item.

### Keep timeline optimistic bubble

Rejected. The goal of this decision is to make server commit state the timeline source and reduce dedupe/reconcile complexity. Keeping optimistic bubble requires `client_request_id`-based reconciliation and makes failure/timeout UX complex again.

### Move stop to REST from the beginning

Rejected. Stop is a latency-sensitive control signal and differs from message/edit/command writes. First scope keeps WebSocket stop, and REST stop migration remains follow-up.

### Transactionally guarantee broker wake-up delivery in API

Rejected. DB commit and broker/signal delivery cannot be tied into one transaction. Input buffer is the source of truth, and signal detection/recovery belongs to worker.

## Consequences

### Expected Benefits

- When user message receives REST success response, it is committed to input buffer.
- First message of a new session follows the same buffer-first path as existing messages.
- Frontend timeline renders only server-authoritative live snapshot, so optimistic/server dedupe is unnecessary.
- `client_request_id` prevents duplicate input buffer during REST retries.
- WebSocket responsibility is reduced to live subscription and stop control.
- ADR-0034 input buffer source-of-truth decision and ADR-0047 canonical history/live protocol decision extend to write boundary.

### Cost and Risks

- Requires message/edit/command REST endpoints and response snapshot model.
- Requires idempotency key store or input buffer/client write request schema.
- Frontend ChatInput/ChatView/useChatSessionContainer write flow changes to async REST mutation.
- Since WebSocket handler removes write path, frontend/backend deployment order must match.
- Browser E2E/testenv verification may be hard to run directly in current agent runtime, requiring GitHub Issue tracking.

## Related Documents

- [ADR-0034: Split chat input buffer into separate RDB table](./0034-chat-input-buffer.md)
- [ADR-0047: Chat protocol uses canonical event history/live API](./0047-chat-protocol-history-live-state.md)
- [ADR-0049: User input boundary FilePart materialization](./0049-user-input-bound-filepart-materialization.md)
- [ADR-0050: Define chat live/history handoff and streaming partial batching](./0050-live-history-projection-handoff-and-stream-batching.md)
- [REST Chat Write Boundary design](../design/rest-chat-write-boundary.md)
