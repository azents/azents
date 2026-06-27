---
title: "File Exchange Storage"
created: 2026-05-10
tags: [backend, engine, frontend]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation, workspace, toolkit]
code_paths:
  - python/apps/azents/src/azents/services/exchange_file/**
  - python/apps/azents/src/azents/services/artifact.py
  - python/apps/azents/src/azents/services/model_file.py
  - python/apps/azents/src/azents/repos/artifact/**
  - python/apps/azents/src/azents/repos/model_file/**
  - python/apps/azents/src/azents/rdb/models/artifact.py
  - python/apps/azents/src/azents/rdb/models/model_file.py
  - python/apps/azents/src/azents/services/session_storage.py
  - python/apps/azents/src/azents/services/uploads/**
  - python/apps/azents/src/azents/services/chat/workspace.py
  - python/apps/azents/src/azents/engine/events/file_parts.py
  - python/apps/azents/src/azents/engine/events/model_file_parts.py
  - python/apps/azents/src/azents/engine/events/model_file_materializer.py
  - python/apps/azents/src/azents/api/public/chat/v1/**
  - python/apps/azents/src/azents/engine/tools/import_file.py
  - python/apps/azents/src/azents/engine/tools/import_resolver.py
  - python/apps/azents/src/azents/engine/tools/present_file.py
  - python/apps/azents/src/azents/engine/tools/read_image.py
  - typescript/apps/azents-web/src/features/chat/hooks/useFileUpload.ts
  - typescript/apps/azents-web/src/features/chat/components/AttachmentPreviewBar.tsx
  - typescript/apps/azents-web/src/features/chat/components/FileAttachmentList.tsx
last_verified_at: 2026-06-27
spec_version: 8
---

# File Exchange Storage

## Overview

File Exchange Storage is the flow that separately stores and retrieves user-facing attachments exchanged between user and Agent, internal Artifacts for agent/tool, and ModelFiles for LLM rich input. User uploads files from chat input, and Agent imports external attachment or internal artifact into sandbox with `import_file`, or exposes sandbox file to user with `present_file`. Generated image/file output is also preserved as provider tool result attachment instead of storing raw base64 directly in event.

## Flows

### User upload to chat

1. azents-web `useFileUpload` sends multipart upload to chat API.
2. API verifies workspace/session access, file size, and media type.
3. Successful upload creates user-facing Exchange attachment and model-input ModelFile/FilePart together. If either cannot be created, upload fails and does not return success response.
4. File body is stored in each store, and attachment URI snapshot and FilePart snapshot remain as independent fields in event/input buffer. Do not reverse-infer FilePart by reading attachment URI.
5. Agent execution loop does not automatically convert attachment to rich file input when transforming user input event to LLM input. Model rich input is delivered only as FilePart content of user input.
6. Exchange attachment has `status`, `expires_at`, and `expired_at` metadata. Scheduler-owned cleanup marks Exchange files past expiration time as `expired` and attempts blob deletion. Resolver, download API, lowerer, and UI treat expired/unavailable as normal history state based on DB availability.

### Agent imports user or internal file

`import_file` tool uses resolver registry by scheme. Supported schemes are `exchange://{object_key}` and `artifact://{storage_key}`. URI is storage location, not entity reference. Do not put business logic that extracts entity id from URI string. Default destination is `/tmp/agent/imports/`, and default destination collisions are deduped with numeric suffix. If explicit destination already exists, fail by default and overwrite only when `overwrite=true`.

`exchange://{object_key}` materializes user-visible attachment into Runtime file. `artifact://{storage_key}` materializes agent/tool internal output Artifact into Runtime file. In both cases, original file body is not directly attached to LLM prompt.

### Agent/tool output artifact

When Agent or MCP-style tool creates internal file artifact, store it as Artifact instead of overloading user-facing attachment. Artifact URI is `artifact://{storage_key}`, and storage key format is `artifacts/{workspace_id}/{session_id}/{created_run_index}/{artifact_id}`. Artifact stores configurable TTL metadata in `expires_at` with default 7 days. Scheduler-owned cleanup marks due Artifacts as `expired` and attempts blob deletion. Resolver rejects access if status is expired regardless of blob existence.

Event transcript keeps only artifact metadata and `artifact://...` URI. Lowerer renders Artifact as bounded metadata text and does not inline raw file body in prompt.

### Explicit FilePart for model rich input

Attachment and Artifact are not automatically converted to ModelFile/FilePart. If model rich input is needed, upload boundary or tool implementation that directly has bytes creates normalized blob in ModelFileStore and returns FilePart. Example is `read_image` tool for showing runtime image bytes to model. A separate FilePart creation tool exposed to model is not current contract. FilePart references ModelFile entity by `model_file_id`, not URI. ModelFile itself does not create URI.

ModelFileStore is model input blob store, not original preservation store. Image ModelFile is normalized to JPEG at creation. Non-image ModelFile is not normalized and only size cap applies. ModelFile has current lifecycle status `available` or `deleted`; persistent run-age degradation and `unreachable` stages are not part of the current lifecycle. Scheduler-owned GC deletes unpinned ModelFiles after their single durable FilePart event falls behind the AgentSession model-input head cursor.
If original non-image payload exceeds size cap, ModelFile is not created and is replaced with user-visible size cap message.

Active transcript FilePart referencing deleted or missing ModelFile is rewritten at pre-lower stage into bounded text placeholder in event payload itself. This rewrite applies equally to user message, assistant message, and client/provider tool result payload, so later compaction, reload, REST/WS projection do not interpret unavailable FilePart as rich input again.

### Agent presents sandbox file

`present_file` tool publishes only files under Provider-reported Agent Workspace as public Exchange attachment to user. Files outside allowed path are rejected. Published attachment appears in chat UI attachment list and can be retrieved through download endpoint.

## Storage Boundaries

- Event store does not store file body. Event has only attachment/artifact metadata and URI reference, or FilePart `model_file_id`.
- Durable event, REST/WS projection, and frontend state do not store raw bytes, inline base64, data URL, or provider-specific file payload.
- There is no implicit conversion among Attachment, Artifact, and ModelFile/FilePart. URI is storage location, not entity reference, so do not add logic extracting entity id from URI string. A `model_file_id` is single-event scoped; reusing the same source bytes later requires materializing a new ModelFile/FilePart.
- Attachment Exchange file and Artifact have time-based retention/TTL lifecycle. ModelFile has context-owned lifecycle based on model-input head cursor reachability and active run pins.
- User upload, agent-presented file, and internal artifact must pass session/workspace ownership verification.
- Sandbox file query is possible only when active sandbox storage handle exists; inactive/hibernated state follows workspace API action contract.
- General presigned upload such as Agent avatar uses `UploadService` category handler, but it is separate category/publish contract from chat exchange file.

## UI Contract

- `AttachmentPreviewBar` provides pre-send file list and removal behavior.
- `FileAttachmentList` renders attachments of user/assistant messages.
- Expired/unavailable attachment keeps metadata card but disables original download/preview action. If only preview asset is unavailable, fallback separately from original attachment download availability.
- Project tab in Session Workspace panel provides only existing Agent Workspace folder registration. Project Source upload/delete/load implementation does not currently exist.

## Related Specs

- Conversation event envelope follows [`../domain/conversation.md`](../domain/conversation.md).
- Session Workspace file/project state follows [`../domain/workspace.md`](../domain/workspace.md).
- Tool execution follows [`agent-execution-loop.md`](agent-execution-loop.md).
