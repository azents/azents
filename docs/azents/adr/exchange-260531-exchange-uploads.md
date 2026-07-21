---
title: "Agent-scoped Exchange Uploads"
created: 2026-05-31
tags: [backend, api, frontend, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: exchange-260531
historical_reconstruction: true
migration_source: "docs/azents/adr/0045-agent-scoped-exchange-uploads.md"
---
# exchange-260531/ADR: Agent-scoped Exchange Uploads

## Status

Accepted.

## Context

Web chat file upload required AgentSession ID through `POST /chat/v1/sessions/{session_id}/upload`. Because of this, attaching a file before sending the first message in a new chat required creating a session before upload or re-querying active session.

This model had these problems:

- From the user's perspective, file upload is Agent/Workspace work, but it required a session identifier.
- If active session re-query right before upload returns a session different from the current screen's session, workspace membership validation runs against the wrong session and can fail with 403.
- `exchange_files` table keeps `agent_session_id` and `agent_runtime_id` as required columns, unnecessarily coupling upload with runtime/session lifecycle.
- It creates the concept of "file list per session," but actual attachments are referenced by messages through `exchange://...` URI. For single-file download/delete access control, file workspace is enough.

## Decision

Exchange upload files are stored as Agent/Workspace-scoped resources.

- Web upload API uses `POST /chat/v1/agents/{agent_id}/upload`.
- Frontend sends only `agentId`, not `sessionId`, on upload.
- Backend looks up Agent by `agent_id` and validates only current user membership in the Agent's `workspace_id`.
- Remove `agent_session_id`, `agent_runtime_id` columns and related indexes/FKs from `exchange_files` table.
- Remove session-scoped upload endpoint and per-session exchange file list endpoint.
- Runtime artifacts are also stored at workspace/agent scope from file metadata perspective. Runtime call context may use session, but exchange file row does not store session/runtime FK.
- Access control for download/delete/attachment resolution is determined by membership in exchange file's `workspace_id`.

## Consequences

- Upload no longer depends on session creation or active session lookup when attaching a file before starting a new chat.
- Upload 403 can be interpreted only as agent workspace membership issue, not session mismatch.
- No API is provided to query file list by session. Message attachment list is represented by `exchange://...` URIs contained in messages.
- Until existing OpenAPI client generates the new endpoint, azents-web upload proxy can call the agent-scoped endpoint through the API client's low-level request.

## Migration provenance

- Historical source filename: `0045-agent-scoped-exchange-uploads.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
