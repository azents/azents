---
title: "ADR-0046 File/Media Resource Lifecycle Implementation Audit Report"
created: 2026-06-02
updated: 2026-06-03
tags: [architecture, backend, frontend, engine, audit]
---

# ADR-0046 File/Media Resource Lifecycle Implementation Audit Report

## Audit Scope

This document rechecks each decision item of [`ADR-0046: Attachment, Artifact, and FilePart lifecycle`](../adr/0046-file-media-resource-lifecycle.md) against current stacked implementation head.

Reference head is `codex/adr-0046-filepart-placeholder-final`, including cumulative state of following stacked PRs.

- `file-media-lifecycle [9/17]: URI file-location semantics`
- `file-media-lifecycle [10/17]: canonical event transport cleanup`
- `file-media-lifecycle [11/17]: canonical attachment and E2E regression coverage`
- `file-media-lifecycle [12/17]: model file reduction lifecycle`
- `file-media-lifecycle [13/17]: final audit and lifecycle cleanup`
- `file-media-lifecycle [14/17]: canonical user input boundary cleanup`
- `file-media-lifecycle [15/17]: frontend canonical chat events`
- `file-media-lifecycle [16/17]: runtime legacy event cleanup`
- `file-media-lifecycle [17/17]: FilePart placeholder rewrite and final verification`
- `file-media-lifecycle follow-up: Attachment lifecycle and availability`
- `file-media-lifecycle follow-up: MCP text resources as artifacts`
- `file-media-lifecycle follow-up: ModelFile unreachable grace`
- `file-media-lifecycle follow-up: Final spec verification and legacy cleanup`

This audit does not make “existing production data migration” a completion condition. Since ADR-0039 private destructive cutover decision remains, ADR-0046 migration rewrite is interpreted to mean that current write/read path no longer creates or long-term supports legacy file/media shape.

## Judgment Criteria

- `[x] Fully applied`: implemented in current production path and major invariant is confirmed by test, type, schema, or scan.
- `[~] Partially applied`: core structure is implemented, but ADR detail requirement, lifecycle detail, migration boundary, UI/API behavior, or verification scope remains.
- `[ ] Not applied`: not implemented in current production path, or implementation state contradicts documented requirement.
- `[!] Decision conflict / needs re-discussion`: ADR body, implementation plan, and follow-up conversation decisions conflict, so current contract must be confirmed before judging completion.

## Overall Judgment

- `[x]` ADR-0046 is fully implemented by current stack.
- `[x]` URI is clarified as `exchange://{object_key}`, `artifact://{storage_key}` file-location semantics.
- `[x]` canonical output part union is organized around `text | attachment | artifact | file` families.
- `[x]` Attachment canonical payload is organized around current shape: `attachment_id`, `uri`, `name`, `media_type`, `size`, `created_at`.
- `[x]` ArtifactStore, `artifact://` resolver, run-age N=2 expiration hook are implemented.
- `[x]` ModelFileStore, upload/tool-boundary FilePart creation, request-local FilePart lowering, ModelFile reduction lifecycle are implemented.
- `[x]` file upload/product E2E verifies canonical user message, raw blob-free payload, REST reload.
- `[x]` worker/run request boundary is cleaned up as `RunUserMessage` canonical input and does not create `UserInputEvent` legacy envelope.
- `[x]` frontend chat event union removed legacy `UserInputEvent`, `ToolCallOutputItem`, `ImageGenerationItemPayload`, `images` wire shape.
- `[x]` runtime legacy event store/classifier/serialization production path is removed; durable broker payload allows only canonical event or explicit stream/control event.
- `[x]` deleted/missing ModelFile FilePart rewrites user/assistant/tool durable payload itself to bounded text placeholder in pre-lower.
- `[x]` `FunctionToolResult` remains only as compatibility input and canonical durable output is saved as current output parts.
- `[x]` Attachment Exchange file retention/TTL, preview MVP metadata, availability status, disabled UI, and expired Exchange lowering are implemented.
- `[x]` MCP file/resource output is artifact-only, including text resources.
- `[x]` ModelFile GC/unreachable/grace-period semantics are implemented with run-boundary deferred delete.
- `[x]` ADR item 14 frontend wire redaction safety-net wording is resolved by 2026-06-03 amendment so raw blob-free event data target takes precedence.
- `[x]` ADR item 12 non-image FilePart age 10 wording is resolved by 2026-06-03 amendment as age 3 unreachable + run-boundary grace GC.

## Latest Decisions

### URI is file-location, not entity reference

- Path under `exchange://` is Exchange object key.
- Path under `artifact://` is Artifact storage key.
- Do not extract entity id from URI.
- If entity reference is needed, keep entity id in separate field in canonical payload.
- Do not maintain aliases such as `exchange://files/{id}`, `artifact://files/{id}`, `exchange://uploads/{id}`, `exchange://artifacts/{id}`.
- ModelFile does not create URI and is referenced only by `model_file_id`.

### Attachment, Artifact, FilePart do not auto-convert

- Attachment is user-agent delivery envelope.
- Artifact is agent/tool output resource.
- FilePart is explicit model rich input.
- lowerer must not auto-convert Attachment/Artifact to FilePart.
- `import_file` is runtime filesystem import tool and does not return FilePart.
- FilePart is created at upload boundary or after tool implementation with direct bytes creates normalized blob in ModelFileStore.

### raw blob-free invariant takes priority over native replay

- durable canonical event, REST/WS projection, frontend state do not store raw bytes, inline base64, data URL, provider-specific file payload.
- `NativeArtifact.item` is adapter-native opaque replay hint, but not raw blob storage.
- raw blob-free cleanup is adapter boundary responsibility, not how canonical core interprets native payload.

### Lifecycle basis

- Attachment Exchange file retention/TTL is implemented with time-based `expires_at` and run preparation cleanup hook.
- Artifact lifecycle is run-age N=2.
- Artifact expiration executes during new run input preparation.
- ModelFile/FilePart reduction age is calculated by turn/run input age.
- image ModelFile normalizes to JPEG and degrades to max edge 1024 at age 1, max edge 300 at age 3.
- image ModelFile becomes unreachable at age 10 and blob access is blocked.
- non-image ModelFile is not normalized, only size cap is applied, and becomes unreachable from age 3.
- unreachable ModelFile is processed as deleted after next run boundary grace and blob delete is attempted.
- Non-image age 10 wording in ADR item 12 was corrected to current contract age 3 unreachable + run-boundary grace GC in 2026-06-03 amendment.
- This audit treats “non-image is not normalized, only size cap is applied, and access is blocked from age 3” as current contract.

## ADR Item-by-item Application Status

### 1. Unify ToolResult shape as Responses function_call_output family

- `[x]` `client_tool_result` and `provider_tool_result` payload are envelope centered on `call_id`, `name`, `status`, `output`.
- `[x]` tool result output is `str | list[ToolOutputPart]` shape.
- `[x]` helper API exists in `output_parts.py`.
- `[x]` canonical output part union is organized around current parts.
- `[x]` lowerer lowers attachment/artifact to bounded text metadata, and file to capability-aware rich input or placeholder.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/types.py`
- `python/apps/azents/src/azents/runtime/canonical/output_parts.py`
- `python/apps/azents/src/azents/runtime/canonical/litellm_responses.py`
- `python/apps/azents/src/azents/runtime/canonical/file_parts.py`

### 2. Existing FunctionToolResult fields are migrated into output parts

- `[x]` `FunctionToolResult.output` is processed as canonical `ToolOutput`.
- `[x]` legacy `content` converts to `OutputTextPart`.
- `[x]` legacy `attachments` converts to `AttachmentOutputPart`.
- `[x]` sink path exists to store binary/image/audio MCP file/resource output as Artifact.
- `[x]` `TextResourceContents` is also stored as UTF-8 Artifact, satisfying “all MCP file output including text file is Artifact”.
- `[x]` `FunctionToolResult` is allowed only as compatibility input, and canonical result payload immediately converts to `ToolOutputPart`.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/tools.py`
- `python/apps/azents/src/azents/runtime/canonical/tools_test.py`
- `python/apps/azents/src/azents/engine/types.py`
- `python/apps/azents/src/azents/engine/tools/mcp_base.py`

### 3. Attachment is Exchange URI based user-agent delivery envelope

- `[x]` Exchange URI is generated as `exchange://{object_key}` file-location.
- `[x]` Attachment canonical payload has `attachment_id`, `uri`, `name`, `media_type`, `size`, `created_at`.
- `[x]` user message and tool result attachment remain metadata delivery envelope, not model rich input.
- `[x]` frontend canonical attachment type also reads direct fields.
- `[x]` preview thumbnail binary asset moved to `preview_thumbnail_uri` instead of inline field; explicit delete/expiration handles original and thumbnail together.
- `[x]` `exchange_files` has `status`, `expires_at`, `expired_at`, and new run preparation marks due files expired.
- `[x]` Preview MVP fields `preview_title`, `preview_summary`, `preview_thumbnail_uri`, `preview_thumbnail_media_type`, `preview_thumbnail_width`, `preview_thumbnail_height`, `preview_generated_at` flow through canonical/runtime/API/frontend state.
- `[x]` Attachment availability queries ExchangeFile row status in resolver and pre-lower filter and reflects expired/unavailable snapshot.
- `[x]` UI preserves unavailable/expired attachment metadata card and disables download/preview actions.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/types.py`
- `python/apps/azents/src/azents/runtime/canonical/engine_adapter.py`
- `python/apps/azents/src/azents/services/input_buffer_promotion.py`
- `python/apps/azents/src/azents/services/exchange_file/__init__.py`
- `python/apps/azents/src/azents/rdb/models/exchange_file.py`
- `python/apps/azents/src/azents/runtime/canonical/filters.py`
- `typescript/apps/azents-web/src/features/chat/types.ts`
- `typescript/apps/azents-web/src/features/chat/hooks/useChatWebSocket.ts`
- `typescript/apps/azents-web/src/features/chat/components/FileAttachmentList.tsx`
- `testenv/azents/e2e/src/tests/azents/public/test_file_upload.py`

### 4. Attachment lowers to text metadata

- `[x]` user message attachment lowers to `[Attachments]` text context.
- `[x]` tool result `AttachmentOutputPart` also lowers to bounded text metadata.
- `[x]` E2E confirms raw file payload does not leak to model request journal.
- `[x]` pre-lower availability filter queries ExchangeFile status and reflects expired/unavailable state in durable payload.
- `[x]` lowerer includes availability in Attachment metadata and marks inaccessible state if unavailable.
- `[x]` Attachment original load failure codes include `expired`, `not_found`, `permission_denied`, `storage_unavailable` families.
- `[x]` UI preserves unavailable card and disables download/preview actions.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/litellm_responses.py`
- `python/apps/azents/src/azents/runtime/canonical/output_parts.py`
- `python/apps/azents/src/azents/runtime/canonical/filters.py`
- `typescript/apps/azents-web/src/features/chat/components/FileAttachmentList.tsx`
- `testenv/azents/e2e/src/tests/azents/public/test_file_upload.py`

### 5. Artifact is agent/tool file output stored in ArtifactStore

- `[x]` Artifact RDB model, repository, service exist.
- `[x]` Artifact URI is `artifact://{storage_key}` file-location.
- `[x]` Artifact output part exists in canonical schema.
- `[x]` MCP binary/image/audio resource output is normalized to artifact output through ArtifactStore sink.
- `[x]` MCP text resource/file output is also normalized to artifact output through ArtifactStore sink.
- `[x]` Artifact can be imported into runtime filesystem with `import_file artifact://...`.
- `[x]` Normal `TextContent` remains conversation text, and only `EmbeddedResource(TextResourceContents)` is considered file resource and becomes Artifact.

Evidence:

- `python/apps/azents/src/azents/rdb/models/artifact.py`
- `python/apps/azents/src/azents/repos/artifact/`
- `python/apps/azents/src/azents/services/artifact.py`
- `python/apps/azents/src/azents/engine/tools/mcp_base.py`
- `python/apps/azents/src/azents/engine/tools/import_resolver.py`

### 6. Artifact lifecycle is run-age based and N is 2

- `[x]` `_ARTIFACT_RETENTION_COMPLETED_RUNS = 2` and `expires_after_run_index = created_run_index + 2` are implemented.
- `[x]` `ArtifactService.expire_for_run_boundary()` marks row expired and attempts blob delete.
- `[x]` `AgentRunExecution` input preparation calls `artifact_expirer` hook.
- `[x]` expired Artifact rejects resolver/download even if blob remains.
- `[x]` blob delete failure is logging-centered in current implementation, but resolver invariant is guaranteed by DB status. Retry queue/metric are later operational reinforcement.

Evidence:

- `python/apps/azents/src/azents/services/artifact.py`
- `python/apps/azents/src/azents/repos/artifact/__init__.py`
- `python/apps/azents/src/azents/runtime/canonical/execution.py`
- `python/apps/azents/src/azents/runtime/canonical/engine_adapter.py`
- `python/apps/azents/src/azents/services/artifact_test.py`
- `python/apps/azents/src/azents/runtime/canonical/execution_test.py`

### 7. Artifact also lowers to text metadata

- `[x]` Artifact output part lowers to bounded text metadata.
- `[x]` expired Artifact is displayed with meaning “expired; no longer accessible”.
- `[x]` Artifact is not automatically converted to rich provider input.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/output_parts.py`
- `python/apps/azents/src/azents/runtime/canonical/litellm_responses.py`

### 8. import_file supports both exchange:// and artifact://

- `[x]` resolver registry supports `exchange` and `artifact` schemes.
- `[x]` resolver returns source URI, source kind, media type, size, bytes.
- `[x]` default destination is `/tmp/agent/imports/`.
- `[x]` output returns imported path, source URI, source kind, media type, size, temporary warning as text.
- `[x]` URI path is treated as storage location and does not create entity-id lookup expectation.

Evidence:

- `python/apps/azents/src/azents/engine/tools/import_file.py`
- `python/apps/azents/src/azents/engine/tools/import_resolver.py`
- `python/apps/azents/src/azents/services/exchange_file/__init__.py`
- `python/apps/azents/src/azents/services/artifact.py`

### 9. FilePart is blob/content part entering LLM input

- `[x]` `FileOutputPart` has `model_file_id`, `media_type`, `name`, `size`, `kind`, metadata.
- `[x]` Both `UserContentPart` and tool output part can represent FilePart.
- `[x]` provider-specific persistent payload is removed by validator.
- `[x]` successful user upload response creates attachment and FilePart together.
- `[x]` tool implementation with direct bytes such as `read_image` creates ModelFile and returns FilePart output.
- `[x]` lowerer does not automatically convert Attachment/Artifact to FilePart.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/types.py`
- `python/apps/azents/src/azents/api/public/chat/v1/__init__.py`
- `python/apps/azents/src/azents/engine/tools/read_image.py`
- `python/apps/azents/src/azents/runtime/canonical/model_file_parts.py`
- `python/apps/azents/src/azents/runtime/canonical/file_parts.py`

### 10. FilePart references normalized blob through ModelFile

- `[x]` ModelFile RDB model, repository, service exist.
- `[x]` ModelFile object key is `model-files/{workspace_id}/{session_id}/{model_file_id}`.
- `[x]` FilePart references `model_file_id`, not ModelFile URI.
- `[x]` image ModelFile is normalized to JPEG.
- `[x]` non-image ModelFile is not normalized; only size cap is applied.
- `[x]` oversized non-image input does not create ModelFile and is replaced by user-visible size cap message.
- `[x]` ModelFile lifecycle separates `unreachable` and `deleted`. Retention threshold, blob missing, decode failure first transition to `unreachable`, and GC to `deleted` occurs after next run boundary grace.
- `[x]` provenance is preserved in `metadata`, FilePart `caption`/`alt_text`, source tool/import metadata. Separate fixed column is not current contract.

Evidence:

- `python/apps/azents/src/azents/rdb/models/model_file.py`
- `python/apps/azents/src/azents/repos/model_file/`
- `python/apps/azents/src/azents/services/model_file.py`
- `python/apps/azents/src/azents/runtime/canonical/model_file_materializer.py`
- `python/apps/azents/src/azents/api/public/chat/v1/__init__.py`
- `python/apps/azents/src/azents/engine/tools/read_image.py`
- `python/apps/azents/src/azents/services/model_file_test.py`

### 11. Lower FilePart right before provider call

- `[x]` request-local ModelFile materializer provides ModelFile blob only to lowerer resolver.
- `[x]` durable event does not store provider-specific `file_data`, `file_id`, base64 field.
- `[x]` image/PDF capability branch and max file bytes budget exist.
- `[x]` unsupported or unavailable FilePart lowers to bounded text placeholder.
- `[x]` provider capability is implemented by capability-aware branch and request size guard in current LiteLLM Responses lowerer. Separate generic provider capability IR is not current contract.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/file_parts.py`
- `python/apps/azents/src/azents/runtime/canonical/model_file_materializer.py`
- `python/apps/azents/src/azents/runtime/canonical/litellm_responses.py`
- `python/apps/azents/src/azents/runtime/canonical/model_file_materializer_test.py`
- `python/apps/azents/src/azents/runtime/canonical/litellm_responses_test.py`

### 12. Reduction reduces context items, and ModelFile blob degrades or GC

- `[x]` `model_file_expirer` hook runs during run input preparation.
- `[x]` image ModelFile degrades to `jpeg:1024` at age 1 and `jpeg:300` at age 3.
- `[x]` image ModelFile becomes unreachable from age 10 and blob access is blocked.
- `[x]` non-image ModelFile becomes unreachable from age 3 and blob access is blocked.
- `[x]` unreachable ModelFile is marked deleted after next run boundary grace and blob delete runs.
- `[x]` degraded ModelFile remains downloadable and can be used for rich input lowering.
- `[x]` deleted/unreachable ModelFile is treated unavailable.
- `[x]` deleted/missing FilePart payload itself in active context is rewritten to bounded text placeholder for all user/assistant/tool payloads in pre-lower transcript rewrite.
- `[x]` non-image age 10 removal wording in ADR body is resolved by 2026-06-03 amendment to current contract age 3 access block.
- `[x]` ADR unreachable status and grace-period delayed GC are implemented based on run boundary.
- `[x]` active context reference based delayed GC was simplified to run boundary grace without separate reference graph per 2026-06-03 amendment.
- `[x]` compaction/file-resource raw blob-free is verified by canonical FilePart validator, lowerer native artifact sanitizer, file resource lifecycle verification, and E2E raw marker assertions.
- `[x]` Therefore ModelFile reduction lifecycle is fully applied by current contract.

Evidence:

- `python/apps/azents/src/azents/services/model_file.py`
- `python/apps/azents/src/azents/repos/model_file/__init__.py`
- `python/apps/azents/src/azents/runtime/canonical/execution.py`
- `python/apps/azents/src/azents/runtime/canonical/filters.py`
- `python/apps/azents/src/azents/runtime/canonical/filters_test.py`
- `python/apps/azents/src/azents/services/model_file_test.py`
- `python/apps/azents/src/azents/repos/model_file/repository_test.py`

### 13. Legacy payload is migration-rewritten to current schema

- `[x]` Existing durable event migration is out of scope under private destructive cutover premise.
- `[x]` current canonical output part union is organized around current schema.
- `[x]` FilePart validator removes provider-specific persistent payload.
- `[x]` file upload E2E verifies user_message payload does not include raw/blob/provider markers.
- `[x]` legacy `EventStore`, `RDBEventStore`, response classifier, legacy durable append path in batch invoke service are removed.
- `[x]` runtime `FunctionToolResult` remains only as compatibility input, and canonical durable payload is stored as current output parts.
- `[x]` `FunctionToolResult(content, attachments)` compatibility bridge is removed, and `FunctionToolResult` allows only current `output`.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/types.py`
- `python/apps/azents/src/azents/runtime/canonical/engine_adapter.py`
- `python/apps/azents/src/azents/services/input_buffer_promotion.py`
- `testenv/azents/e2e/src/tests/azents/public/test_file_upload.py`

### 14. Frontend wire redaction / raw blob-free event data

- `[x]` canonical event payload removes FilePart provider payload.
- `[x]` Attachment thumbnail is delivered as `preview_thumbnail_uri`, not inline `thumbnail` field.
- `[x]` REST/WS upload E2E verifies canonical payload raw marker absence.
- `[x]` frontend canonical attachment mapper reads direct current fields.
- `[x]` frontend chat WebSocket state handles durable file/media/user/tool output as canonical `kind/payload` event.
- `[x]` `WireAttachment`, `UserInputEvent`, `ToolCallOutputItemPayload`, `ImageGenerationItemPayload`, legacy `images` field are removed from frontend legacy event union.
- `[x]` broker serialization accepts only canonical event and explicit stream/control event, rejecting legacy `Event` envelope.
- `[x]` `wire_sanitization` safety-net wording in ADR body is resolved by 2026-06-03 amendment. Current contract guarantees raw blob-free event data so frontend file/media compatibility sanitization is unnecessary.

Evidence:

- `python/apps/azents/src/azents/runtime/canonical/types.py`
- `typescript/apps/azents-web/src/features/chat/types.ts`
- `typescript/apps/azents-web/src/features/chat/hooks/useChatWebSocket.ts`
- `testenv/azents/e2e/src/tests/azents/public/test_file_upload.py`

## Current Blockers / Gaps

No blockers/gaps by ADR-0046 current contract.

Operational reinforcement candidates:

- Add artifact/model-file blob delete retry queue and metric.
- Extend detailed provider-specific file capability matrix as live provider coverage grows.

## Legacy Compatibility Layers That Became Duplicate Concepts

### Legacy `Event(UserInputEvent)` input bridge

- Location: `python/apps/azents/src/azents/worker/engine.py`
- Location: `python/apps/azents/src/azents/runtime/canonical/engine_adapter.py`
- Location: `python/apps/azents/src/azents/services/input_buffer_promotion.py`
- Duplicated current concept: canonical `user_message` event and `UserMessagePayload`.
- Status: removed. `RunRequest.user_messages` receives `RunUserMessage`, and worker direct input and input buffer promotion directly create canonical `UserMessagePayload`.

### Legacy frontend event payload union

- Location: `typescript/apps/azents-web/src/features/chat/types.ts`
- Location: `typescript/apps/azents-web/src/features/chat/hooks/useChatWebSocket.ts`
- Location: `typescript/apps/azents-web/src/features/chat/hooks/useSubagentSession.ts`
- Duplicated current concept: canonical chat events and engine control events.
- Removal reason: if file/media current schema coexists with legacy `images`/tool output shape, raw blob-free invariant verification scope keeps expanding.
- Status: file/media durable payload union removed. Frontend separately handles canonical durable event and explicit stream/control event.

### Legacy runtime event serialization

- Location: `python/apps/azents/src/azents/broker/serialization.py`
- Location: `python/apps/azents/src/azents/engine/events/legacy.py`
- Location: `python/apps/azents/src/azents/engine/types.py`
- Duplicated current concept: canonical events plus explicit stream projection/control events.
- Removal reason: ADR-0046 Attachment/Artifact/FilePart semantics can be collapsed again into legacy `ToolCallOutput(content, attachments)`.
- Status: removed from production durable serialization path. `engine/events/legacy.py` remains only as stream/control projection dataclass module.

### Compatibility `FunctionToolResult`

- Location: `python/apps/azents/src/azents/engine/types.py`
- Location: `python/apps/azents/src/azents/runtime/canonical/tools.py`
- Duplicated current concept: `ToolOutput = str | list[ToolOutputPart]`.
- Removal reason: new tools should directly return current output parts. But it can be temporarily kept only at external compatibility boundary.

## Verification Evidence

Major verifications confirmed in current stack:

- `python/apps/azents` ruff/pyright/pre-commit hooks.
- `testenv/azents/e2e` file upload E2E with raw blob-free assertions.
- chat persistence E2E with canonical durable event kind assertions.
- input buffer E2E with canonical `user_message`/`client_tool_call` expectations.
- ModelFile service/repository unit tests for normalization, size cap, degradation, and run-boundary lifecycle.
- Artifact service/runtime verification tests for artifact URI, expiration, and import.

CI status is checked separately in each stacked PR. This document is an audit reference document and does not replace CI green itself.
