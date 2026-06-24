---
title: "ADR-0049: User Input Boundary FilePart Materialization"
created: 2026-06-04
tags: [architecture, backend, frontend, engine, security]
---
# ADR-0049: User Input Boundary FilePart Materialization

## Status

Accepted.

## Context

ADR-0045 decided to change Web upload to agent-scoped Exchange upload instead of session-scoped upload. ADR-0046 separated Attachment, Artifact, FilePart, and ModelFile lifecycles. However, current implementation mixes these boundaries again:

- Upload API returns both Exchange attachment and `file_part`.
- Frontend stores `file_part` from upload response and sends it again as `file_parts` in WebSocket message payload.
- Backend chat request trusts client-provided `file_parts` and puts them into user input.
- Exchange attachment resolution globally looks up object key first, then checks only workspace membership.
- ModelFile lookup also queries by ID without current agent namespace.

This creates two problems.

First, upload and user input creation have different lifecycles. Upload creates an Exchange attachment in an agent namespace, and session or user input may not exist yet. FilePart, on the other hand, is an abstraction for model input content part and should be created only when user input is created.

Second, file identity is interpreted outside agent namespace. If agent A/B in the same workspace reference the same `exchange://...` string or `model_file_id`, global lookup followed by only workspace permission check can cause cross-agent leakage. This cannot be solved by a permission-denied hotfix. Resolution must not see outside the current agent at namespace resolution stage.

## Decision

Limit responsibility for creating FilePart from file attachment to the user input boundary.

- Upload API returns only Exchange attachment metadata. It does not return `file_part`.
- WebSocket `message` / `edit_user_message` requests accept only `attachments`. Client-provided `file_parts` is removed from public contract.
- Frontend sends `uri` from upload response as `attachments`. It does not store or send FilePart.
- Backend resolves attachment URI when creating user input, using current `agent_id`, finalized `session_id`, and `user_id`.
- Only at this boundary does Exchange URI attachment materialize into FilePart. General attachment metadata resolve, preview, download, import, and delete do not convert attachment into FilePart.
- User input payload may contain both attachment snapshot and FilePart snapshot. In that case, FilePart is backing for model rich input of that user input.
- Exchange URI resolution happens only inside the current agent namespace. Cross-agent object keys are excluded as not found during current agent namespace lookup, not found globally and then rejected with 403.
- ModelFile lookup/download also gets paths that accept current agent namespace, and model request materialization finds ModelFile only in that agent namespace.
- ModelFile is FilePart backing storage. It is not created at upload time or as an independent entity without FilePart.

## Considered options

### Option A — keep creating FilePart at upload and strengthen permission checks

We could keep the existing structure and add `file_parts` validation. But the client would still carry model input parts, and lifecycle mixing between upload and user input remains. Cross-agent reference also tends to remain as lookup then permission check. Not adopted.

### Option B — always convert attachment into FilePart

Creating FilePart on every Exchange attachment resolve path may look simple. But Attachment is a user-agent delivery envelope, while FilePart is a model input part. If general attachment operations such as download/preview/import create model input storage, the domain boundary breaks again. Not adopted.

### Option C — materialize only at user input boundary

Upload creates only Exchange attachment. When user input creation starts, resolve URI in current agent/session/user namespace and create necessary FilePart. General attachment path and model input path stay separated, and current agent namespace lookup can be enforced. Adopted.

## Consequences

- File upload in new chat remains possible without session.
- ModelFile does not exist immediately after upload. ModelFile/FilePart is created when user input is created through message send/edit.
- FilePart disappears from frontend state and WebSocket payload.
- Backend runtime direct input, input buffer promotion, and edit path must all use server-side materialization helper.
- Exchange/ModelFile service must provide agent-scoped lookup APIs.
- Even if a legacy client sends `file_parts`, the new public schema ignores or rejects it during validation. Production path does not trust client-provided FilePart.
