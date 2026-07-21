---
title: "WebSocket write stale design inventory"
created: 2026-06-05
tags: [documentation, frontend, backend]
---

# WebSocket write stale design inventory

After the REST chat write transition, the current contract is owned by `spec/domain/conversation.md` and `spec/flow/agent-execution-loop.md`. Web chat message/edit/command writes use only REST commit endpoint, and WebSocket is responsible only for existing session live subscription and stop control. The `/chat/v1/sessions/new` WebSocket first-message route is not the current write or subscription contract.

The design documents below are development-time records, so they are not directly updated after implementation completes. When reading them, prioritize current specs and [rest-260605/ADR](../adr/rest-260605-rest-chat-write-boundary.md).

- `docs/azents/design/file-260505-file-exchange.md`: still contains old flow describing attachment URI included in WebSocket chat message.
- `docs/azents/design/architecture.md`: still contains old sequence where client sends message payload through WebSocket.
- `docs/azents/design/chat-input-buffer.md`: still contains old sequence sending `ChatMessageRequest` as WebSocket write.
- `docs/azents/design/file-260301-file-support.md`: still mentions old write surface centered on `ChatMessageRequest.attachments`.
- `docs/azents/design/responses-api-migration.md`: still contains old sequence `Client->>WS: ChatMessageRequest`.
- `docs/azents/design/server-260311-server-side.md`: still contains `/sessions/new?ticket=...` WebSocket first-message creation flow.
- `docs/azents/design/user-input-bound-filepart-materialization.md`: still contains WebSocket message/edit request attachment flow.

Cleanup criteria:

- ADRs are append-only decision records, so do not modify them.
- Implemented designs remain development-time design records.
- Current behavior explanation is integrated into specs.
- In new implementation/review, do not use WebSocket write descriptions in the designs above as evidence.
