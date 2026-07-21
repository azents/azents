---
title: "Agent File Exchange Storage Phase 1 — Backend Foundation"
tags: [backend, api, engine]
created: 2026-05-05
updated: 2026-05-05
implemented: 2026-05-05
document_role: supporting
document_type: supporting-phase
migration_source: "docs/azents/design/agent-file-exchange-storage-phase1-backend-foundation.md"
---

# Agent File Exchange Storage Phase 1 — Backend Foundation

## 1. Goal

Phase 1 adds backend foundation for Exchange Storage. This phase is the minimum unit that changes Web upload and runtime attachment input to `exchange://uploads/{file_id}`.

## 2. Data Model

The `exchange_files` table connects object storage key with permission/display metadata.

| Field | Description |
|---|---|
| `id` | stable ID of `exchange://uploads/{id}` or `exchange://artifacts/{id}` |
| `workspace_id` | top-level permission boundary |
| `agent_session_id` | Web/raw session event association |
| `agent_runtime_id` | sandbox/import/export association |
| `agent_id` | Agent association |
| `origin_type` | `upload` or `artifact` |
| `object_key` | S3 object key, must not be externally exposed before DB lookup |
| `filename`, `media_type`, `size_bytes`, `sha256` | display/verification metadata |
| `created_by_user_id`, `created_at` | creator and creation time |

For upload, object key uses `exchange/{workspace_id}/uploads/{file_id}/original`.

## 3. Service API

`ExchangeFileService` coordinates S3 and repository.

- `create_upload(session_id, user_id, filename, media_type, body)`
  - Verifies session and workspace membership.
  - Stores S3 object and creates metadata row.
  - `ExchangeFile.uri` returns `exchange://uploads/{file_id}`.
- `list_files(session_id, user_id, origin_type)`
  - Verifies session workspace access and returns only non-deleted files.
- `download(file_id, user_id)`
  - Verifies workspace permission through DB metadata, then returns S3 bytes.
  - Returns `FileUnavailable` if object disappeared.
- `delete(file_id, user_id)`
  - Deletes object and metadata row after permission check.

## 4. Public API

- `POST /chat/v1/sessions/{session_id}/upload`
  - Keeps existing multipart path.
  - Response includes `uri`, `media_type`, `size`, and `name`.
- `GET /chat/v1/sessions/{session_id}/exchange-files?origin_type=upload|artifact`
- `GET /chat/v1/exchange-files/{file_id}/download`
- `DELETE /chat/v1/exchange-files/{file_id}`

Legacy `/session-data` and `/shared-data` endpoints are removed in later cleanup phase.

## 5. Runtime Attachment Resolver

`resolve_invoke_input` recognizes `exchange://uploads/{file_id}`.

- Image files pass object bytes to LLM image input and create thumbnail snapshot.
- Non-image files do not inject bytes directly into LLM; keep only filename/media_type/size/URI metadata preview.
- Legacy absolute path attachment remains as existing File API fallback and is removed in later phase.

## 6. Verification

- Exchange URI parser and service permission/metadata/S3 interaction unit tests
- Existing AgentRuntimeService / resolver regression tests
- nointern ruff, format, pyright
- public OpenAPI regeneration
