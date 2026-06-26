---
title: "ADR-0046: Attachment, Artifact, and FilePart lifecycle"
created: 2026-06-01
tags: [architecture, backend, frontend, engine]
---
# ADR-0046: Attachment, Artifact, and FilePart lifecycle

## Status

Accepted.

## Amendments 2026-06-26

- Lifecycle cleanup is scheduler-owned rather than run-loop-owned. Normal Agent run input preparation no longer synchronously expires Exchange files, Artifacts, or ModelFiles.
- The scheduler uses explicit latest run indexes from `agent_runs` to preserve Artifact and ModelFile run-age semantics; it does not infer entity ids or run context from URI strings.
- Blob deletion is retried through later scheduler passes. Rows record `blob_deleted_at` only after object deletion succeeds; deletion failure is logged and remains retryable while user-facing access is denied by lifecycle status.

## Amendments 2026-06-03

Original text of this ADR preserves the proposed direction at decision time. During later full migration implementation, this current contract was confirmed:

- Frontend wire redaction is not primary design. Target is to ensure durable canonical event, REST/WS projection, and frontend chat state do not contain raw bytes, inline base64, data URL, or provider-specific file payload. For chat file/media path where raw blob-free invariant is guaranteed, frontend compatibility sanitization layer is not kept.
- Non-image ModelFile/FilePart is not normalized and only size cap applies. From age 3, mark `unreachable` to block model rich input access, and after next run-boundary grace transition to `deleted` and try blob delete.
- Image ModelFile degrades to `jpeg:1024` at age 1, `jpeg:300` at age 3, and becomes `unreachable` from age 10. It transitions to `deleted` after next run-boundary grace.
- Delayed GC is implemented as run-boundary grace instead of separate active-reference graph. Separation between `unreachable` and `deleted` immediately blocks current model input while deferring blob deletion to next boundary.
- Provider capability matrix is implemented as capability-aware branch of current LiteLLM Responses lowerer. No separate generic request IR/compiler layer is created.
- URI is storage location, not entity reference. No business logic extracts entity id from URI string in any URI scheme. If entity reference is needed, use separate id field.
- User upload success response is returned only when Exchange attachment and ModelFile/FilePart are created together. User input preserves attachment URI snapshot and FilePart snapshot as independent fields. Attachment is not converted into FilePart later.
- Model-exposed FilePart creation tool is not current contract. FilePart creation happens at upload boundary or when tool implementation that already has bytes, such as `read_image`, intentionally wants model rich input.
- ModelFile does not create URI. FilePart references ModelFile entity by `model_file_id`; URI is used only when file access such as runtime import/download is needed.

## Context

Recently image generation/input payloads were exposed as inline base64 in frontend wire payload and context inspector raw event, so redaction based on `sanitize_frontend_dict` was added. This hotfix protects browser memory and WebSocket payload, but root problem is that user-agent file delivery, agent/tool file outputs, and LLM input file parts are mixed in same payload space.

Initial assumption was: "images small enough to enter LLM input are probably fine to round-trip through RDB row and message payload." Codex and anomalyco/opencode research shows data URL/base64 patterns are common at model request layer, but guardrails such as resize, omit, strip, count-only telemetry also exist.

Azents crosses cloud runtime, RDB, broker, WebSocket, browser UI, context inspector, agent runtime, and MCP tool, so file/media concepts must be clearly separated.

This ADR separates these lifecycles:

- Attachment lifecycle: user-agent file delivery envelope. It contains Exchange URI and becomes basis for UI preview/download and runtime import/export. Actual exchange file may expire independently from event lifecycle.
- Artifact lifecycle: file output resource produced by agent/tool. Stored in ArtifactStore and accessed with `artifact://` URI. It is neither user-facing attachment nor LLM rich input FilePart. It is valid during creation run and next 2 completed runs, then expires/deletes.
- FilePart lifecycle: blob/content part that can directly enter LLM input. Same schema is used in input message and tool result output. It lowers to native rich content part such as `input_image`, `input_file` when provider request is built.
- ModelFile lifecycle: provider-neutral normalized blob identity referenced by FilePart. Stored in ModelFileStore. It is not original archive; it is normalized blob for model input budget management.

`exchange://` is backend-agnostic file exchange abstraction, not storage backend. Even if backend changes from S3 to filesystem, external scheme need not change. Exchange file has retention independent from event lifecycle and can expire later. Therefore load/download may fail even if Exchange URI remains in event/message.

`artifact://` is also backend-agnostic internal artifact address. Physical backend of ArtifactStore can be filesystem, S3-compatible object storage, or custom adapter. It may share physical backend with Exchange, but logical namespace, lifecycle, and access path are separate.

## Decision Drivers

- Must expand beyond images to normal files, large text output, binary, MCP file output.
- User-facing delivery, agent working output, and LLM rich input must not be mixed as same concept.
- Tool result schema should be identical or similar to Responses `function_call_output` shape.
- Large tool output payload must not be unboundedly inlined into prompt/canonical.
- Attachment and Artifact must not automatically lower into LLM rich file input.
- Blob directly entering LLM input must be unified as FilePart.
- FilePart bytes or materialization source must not be inlined in RDB/event payload.
- Exchange URI load failure, Artifact expiration, and ModelFile GC must be treated as normal cases.
- Frontend payload redaction should remain safety net, not primary design.

## Proposed Direction

### 1. Unify ToolResult shape with Responses function_call_output family

Tool result in every layer uses envelope identical or similar to Responses `function_call_output`.

Base fields:

- `call_id`: required at every layer. Matches provider function call and result.
- `output`: required at every layer. string or content part list.
- `status`: required in canonical. Optional at tool function boundary; default `completed`. Represents tool execution lifecycle state.
- `name`: required in canonical. Can be filled by tool registry/executor and used by UI/debug/hook context. Not included in native lowering.
- `id`: optional. Used only if native compatibility/replay is needed.

`output` is one of:

- string
- content part list

Canonical also keeps this shape. Simple text-only tool result can be stored as string, and content part list is used only when structured output is needed. This prevents tool function authors from wrapping common text result in part list every time.

Canonical output part is more semantic and provider-neutral than provider-native part. Canonical output part union for content part list has four variants:

- `text`
- `attachment`
- `artifact`
- `file`

Lowerer maps canonical output part to provider-native output part:

- `text` lowers to native text part such as Responses `input_text`.
- `attachment` lowers to bounded text metadata part, not rich file input.
- `artifact` lowers to bounded text metadata part, not rich file input.
- `file` lowers to native rich content part such as Responses `input_image`, `input_file` according to provider capability and media type.

If provider does not support rich output part or policy forbids direct insertion, lower to bounded text metadata part.

Canonical storage keeps `output: str | content part list`, but consumers use helper API rather than branching directly. Helper is placed at canonical/runtime boundary, e.g. `azents.runtime.canonical.tools` or `azents.runtime.canonical.output_parts`.

Required helpers:

- `iter_output_parts(output)`: if `str`, iterate like synthetic `text` part.
- `append_output_part(output, part)`: if adding part to standalone `str`, promote to `[text, part]`.
- `output_text_preview(output, max_chars)`: create bounded preview for UI/lower/debug.

Helpers do not change storage shape; they only provide view/operation.

### 2. Existing FunctionToolResult fields migrate into output parts

Existing `FunctionToolResult(content, attachments, images)` migrates to new ToolResult shape.

- `content` becomes `output` string if text-only result.
- If `content` exists with other parts, it becomes `text` output part.
- `attachments` migrate to `attachment` output part.
- `images` migrate to `file` output part.
- `images` are deprecated.
- New tools return `output: str | content part list` directly rather than distributed `content`, `attachments`, `images`.
- MCP tool file output, including text file, returns as `artifact` output part.

This migration is for legacy compatibility. In new design, user-facing delivery is `attachment`, agent/tool file output is `artifact`, and LLM rich input is explicitly `file`.

### 3. Attachment is Exchange URI based user-agent delivery envelope

Attachment is envelope for file exchange between user and agent.

- Has Exchange URI.
- Target of UI preview/download.
- Imported into runtime with `import_file exchange://...`.
- Not LLM rich file input.
- Not automatically converted to FilePart.

Attachment has display metadata snapshot from event time. Required fields:

- `attachment_id`
- `uri`
- `name`
- `media_type`
- `size`
- `created_at`

Recommended/contextual fields:

- `source`: `user_upload | tool_output | generated | imported`
- `exchange_key` or exchange internal locator
- `availability`

This metadata does not guarantee file load availability. Exchange URI can fail after retention. Exchange availability is state checked at query time; unavailable/expired is normal case.

Title, thumbnail, text summary and similar display aids are generalized as Preview. Conceptually Preview is subentity of attachment, but DB implementation may use `preview_*` columns instead of separate table.

Preview MVP fields:

- `preview_title`
- `preview_summary`
- `preview_thumbnail_uri`
- `preview_thumbnail_media_type`
- `preview_thumbnail_width`
- `preview_thumbnail_height`
- `preview_generated_at`

Preview fields are nullable snapshots. Preview generation failure status is not stored in MVP. Log/trace is enough; no preview means no preview.

Binary preview asset such as thumbnail is not inlined into event payload. It is stored together in file storage backend and may disappear with original file retention/delete. UI treats preview load failure as normal case.

### 4. Attachment lowers to text metadata

Attachment output part does not lower to provider rich `input_file`/`input_image`. Lowerer represents Attachment as bounded text metadata.

Lowered metadata can include:

- name
- media type
- size
- Exchange URI
- preview title/summary
- availability status
- instruction to use `import_file` if needed

Thumbnail URI is UI asset, so not included by default in LLM lower metadata.

If Exchange file is expired/unavailable, lowerer displays inaccessible state with metadata. Even if URI and metadata remain, model must not treat it as usable file. Lowering focuses on original availability and generally does not emphasize preview failure.

Attachment original load failure codes:

- `not_found`
- `expired`
- `permission_denied`
- `storage_unavailable`

Preview load failure is represented as `preview_unavailable` with optional cause `not_found | expired | storage_unavailable`. UI keeps unavailable attachment card but disables download/preview action. If only preview is unavailable, download remains and only preview falls back.

### 5. Artifact is agent/tool file output stored in ArtifactStore

Artifact is redefined as file output resource produced by agent/tool, not old model-context file record.

- Stored in ArtifactStore.
- URI scheme is `artifact://`.
- Not Attachment.
- Not FilePart.
- Not exposed as UI download card by default.
- Not automatically lowered into LLM rich file input.
- Content access copies it into runtime filesystem using `import_file artifact://...`, then uses file tools.

All file outputs from MCP tools are unified as Artifact. Text output is also Artifact if it is file output. For example, if GitHub MCP returns repository file content, do not inline into prompt or expose as Attachment; store in ArtifactStore, then lower only `artifact://` URI and bounded metadata.

This policy solves:

- prevents token explosion from large text/file output.
- avoids polluting Attachment UI download UX.
- allows file output to be imported into runtime filesystem for partial read/search/copy when needed.
- controls blob accumulation through ArtifactStore lifecycle.

### 6. Artifact lifecycle is run-age based with N=2

Artifact is valid for up to 2 completed runs after creation.

Definition:

- valid in run where artifact is created.
- valid for next 2 completed runs.
- valid when `current_run_index - created_run_index <= 2`.
- expired from following run.

Example:

- created at run 10: valid in run 10, 11, 12
- expired from run 13

Expired means deleted and inaccessible. Expired artifact may still have metadata and URI when lowered, but is displayed as expired. `import_file artifact://...` access must fail.

Artifact lifecycle is deterministic run-age expiration. No separate GC lifecycle. At run boundary where `current_run_index > expires_after_run_index`, artifact expires and blob is deleted. Row or event metadata may remain for history/display, but content must be inaccessible. Even if blob deletion operationally fails, resolver must deny access to expired artifact.

Expired artifact metadata remains in canonical history. Event payload is not rewritten to preserve meaning of past tool output transcript. Only content/blob access is unavailable; lowerer and resolver query current artifact status to show expired status and deny access.

Delete failure is not artifact lifecycle state. At run boundary, mark expired, try blob delete, and handle failure via operational log/metric/retry queue. Core invariant: if status is expired, resolver denies access regardless of blob existence.

Required Artifact metadata:

- `artifact_id`
- `uri`
- `workspace_id`
- `session_id`
- `created_run_id`
- `created_run_index`
- `expires_after_run_index`
- `name`
- `media_type`
- `size`
- `storage_key`
- `status`
- `created_at`

Artifact status is `available | expired`. Delete failure is operational retry/logging, not artifact lifecycle state.

Artifact URI is `artifact://{storage_key}` file-location address. Resolver looks up URI path as ArtifactStore storage key and verifies workspace/session permission with DB metadata. URI is not entity reference; payloads that reference Artifact have separate `artifact_id` field.

ArtifactStore object key is `artifacts/{workspace_id}/{session_id}/{created_run_index}/{artifact_id}`. Filename is not in object key; it is stored only in metadata `name`.

Optional metadata:

- `sha256`
- `source_tool_name`
- `source_call_id`
- `source_part_index`
- `description`
- `preview_title`
- `preview_summary`
- `line_count`
- `metadata`

### 7. Artifact also lowers to text metadata

Artifact output part does not lower to provider rich `input_file`/`input_image`. Lowerer represents Artifact as bounded text metadata.

Lowered metadata can include:

- artifact URI
- name
- media type
- size
- created run
- expiration status
- remaining runs or expired status
- instruction to use `import_file` if needed

Expired artifact is displayed as “expired; no longer accessible”. Model must not treat expired artifact as usable file.

### 8. import_file supports both exchange:// and artifact://

`import_file` copies file resource addressed by URI into runtime filesystem.

Supported:

- `exchange://...`
- `artifact://...`

`import_file` uses resolver registry per scheme. MVP resolver supports `exchange://` and `artifact://`. Each resolver handles URI parse, permission/session/workspace verification, availability check, metadata query, blob access.

Common resolver result provides:

- bytes or stream
- name
- media type
- size
- source URI
- source kind: `exchange | artifact`

If previous default destination was upload-biased like `/tmp/agent/uploads/`, change to `/tmp/agent/imports/`. If user does not specify destination path, save under this directory with sanitized source metadata name.

`import_file` standardizes failure codes:

- `invalid_uri`
- `unsupported_scheme`
- `not_found`
- `expired`
- `permission_denied`
- `storage_unavailable`

Expired artifact denies access regardless of blob existence. Expired exchange file is also normal failure case.

`import_file` output returns imported path, source URI, source kind, media type, size, temporary path warning as text. It does not return file itself as attachment, artifact, or file part. MVP does not create sidecar `.meta.json` file. Provenance may be stored in runtime internal log/trace if needed, but sidecar metadata next to file is post-MVP option.

In default import directory, filename conflict appends numeric suffix to sanitized basename, e.g. `file.txt`, `file-1.txt`, `file-2.txt`. Explicit destination path that already exists fails by default. Overwrite is allowed only with explicit `overwrite: true`. Source filename is sanitized to prevent path traversal.

### 9. FilePart is blob/content part entering LLM input

FilePart is blob/content part that can directly enter LLM input. Role previously assumed by Artifact as “file part entering LLM input” is unified as FilePart.

- user input uses FilePart.
- tool result output can also use FilePart.
- same or similar schema is used in input and output.
- lowers 1:1 to native rich content part during provider lowering.
- In Responses terms, becomes `input_image`, `input_file`, etc.

Minimal fields:

- `type: "file"`
- `model_file_id`
- `media_type`

Recommended fields:

- `name`
- `size`
- `kind`

`kind` is broad category to simplify provider capability, UI, placeholder handling. MVP examples: `image`, `document`, `text`, `binary`. `kind` is snapshot derived from media type rather than source of truth.

Optional fields:

- `detail`
- `caption`
- `alt_text`
- `metadata`

FilePart does not store raw bytes, base64, provider-specific `file_data`, provider-specific `file_id`, provider-specific serialized payload. Provider-specific payload is created request-locally by lowerer immediately before request.

FilePart differs from Attachment and Artifact.

- Attachment is user-agent delivery envelope.
- Artifact is agent/tool file output resource.
- FilePart is rich input part visible directly to LLM.

Attachment or Artifact does not automatically become FilePart. To put file into LLM input, explicit FilePart must exist.

### 10. FilePart references normalized blob through ModelFile

FilePart bytes or provider input materialization source is not inlined in RDB/event payload. FilePart references provider-neutral normalized blob in ModelFileStore through ModelFile.

Purpose of ModelFileStore is model input preservation and provider call lowering, not user download. ModelFileStore stores normalized blob for model-input, not original file. Original preservation is not ModelFile responsibility.

Use these paths for original:

- Attachment Exchange URI
- Artifact Artifact URI
- runtime path
- tool flow

At ModelFile creation, provider-neutral normalized blob is created. Provider adapter lowers FilePart and normalized blob or metadata from ModelFileStore to provider-specific serialized payload immediately before call. Provider-specific additional derivative can be lazy-created, but does not depend on original Exchange URI or Artifact URI.

Required ModelFile metadata:

- `model_file_id`
- `workspace_id`
- `session_id`
- `media_type`
- `kind`
- `size`
- `storage_key`
- `created_at`
- `status`
- `normalized_format`

ModelFile status is `available | degraded | unreachable | deleted`. Unlike Artifact, ModelFile has delayed reachability-based GC, so `unreachable` and `deleted` are separated.

ModelFileStore object key is `model-files/{workspace_id}/{session_id}/{model_file_id}`. Filename is not in object key and is stored only in metadata `name`.

Optional metadata:

- `name`
- `sha256`
- `source_kind`: `attachment | artifact | runtime | generated | tool`
- `source_uri`
- `width`
- `height`
- `token_estimate`
- `caption`
- `metadata`

`source_uri` is provenance only, not materialization dependency. It is not responsible for restoring original. `normalized_format` indicates provider-neutral normalized blob format and must be stored.

ModelFileStore owns put/get/replace/delete/exists.

### 11. FilePart lowers immediately before provider call

Provider adapter lowers FilePart to provider-specific serialized payload. FilePart lowering branches by resolved model capabilities, not provider name. Capability resolution is done by provider adapter/native lowerer.

Capability examples:

- `supports_image_input`
- `supports_file_input`
- `supports_pdf_input`
- `supports_text_file_input`
- `supported_media_types`
- `supports_file_id`
- `supports_file_data`
- `supports_file_url`
- `max_request_bytes`
- `max_file_bytes`
- `max_image_pixels`

Canonical FilePart stays provider-neutral. Lowerer inspects model capability and MIME media type to choose native part.

- Image FilePart lowers to native image input if model supports image input.
- Text/document FilePart lowers to native file input if model supports file input and MIME type is allowed.
- Binary/unknown FilePart is not lowered to native input unless model capability explicitly supports it.
- If capability is absent or budget is exceeded, lower to bounded text placeholder instead of silent omit.

Placeholder includes name, media type, size, kind, caption/alt_text if present, unavailable reason.

Provider-specific serialized payload is not persisted in canonical payload. Canonical keeps FilePart and ModelFile reference, and provider-specific payload is created only when native request is built. Provider-specific derivative cache is allowed but not canonical source of truth.

Budget is enforced in two stages:

- First apply normalized blob budget at ModelFile creation.
- Second apply request total bytes, per-file bytes, image dimensions, supported MIME types according to resolved model capability during native request lowering.

On budget exceed, image is degraded/resized when possible. Non-image FilePart should exist only if it passed max size cap at creation; if it exceeds model capability budget at lower time, lower to bounded text placeholder. Request failure is last resort. Lowerer does not arbitrarily replace with Artifact.

### 12. Reduction reduces context item, ModelFile blob degrades or GC's

Turn-based reduction/compaction is not lifecycle owner of Attachment or Artifact.

- Attachment follows Exchange lifecycle.
- Artifact follows run-age lifecycle.
- FilePart/ModelFile follows model context reduction lifecycle.

Reduction decides which FilePart and text context remain in turn/context. ModelFile itself is not source of truth for reduction judgment. ModelFile is normalized blob identity referenced by FilePart and becomes GC target when no longer referenced by active context item.

ModelFileStore normalized blob is not original archive, so it may be destructively degraded by reduction age. Existing `CanonicalImageLifecycleFilter` inline data URL rewrite policy moves to ModelFileStore normalized blob lifecycle policy in new structure.

Image ModelFile default degradation inherits existing policy:

- age 1: degrade to max edge 1024 JPEG.
- age 3: degrade to max edge 300 JPEG.
- age 10: replace/remove FilePart with placeholder and cut ModelFile reference.
- JPEG quality uses existing value 85.
- On resize/decode failure, can replace with placeholder.

Non-image FilePart applies max size cap at creation time. MVP default cap is 1MB. Cap can be overridden by workspace/model config, but files over cap are not created as FilePart. Lowerer or reduction does not arbitrarily replace with Artifact.

Non-image FilePart does not reprocess blob for degradation. At age 10, replace/remove FilePart with placeholder and cut ModelFile reference. Placeholder keeps only bounded filename-centered metadata:

- name
- media type
- size

Original restore is not ModelFile responsibility. It can be attempted only through Attachment/Exchange, Artifact/import_file, runtime/tool path.

Summary does not include FilePart blob. Summary may include only bounded metadata:

- name
- media type
- size
- caption/alt_text
- status such as `file removed from active context`

Summary does not newly resolve or import Attachment/Artifact URI. If user references old file again, access is possible only through explicit `import_file` flow when Attachment URI remains and is available. Artifact is inaccessible when expired. ModelFile is not restored from summary. Summary is memory/explanation mechanism, not restore mechanism.

ModelFile GC principles:

- Reduction does not immediately delete ModelFile blob; it marks unreferenced ModelFile as unreachable/compacted.
- Actual ModelFileStore blob deletion is delayed by GC.
- GC targets ModelFile not referenced through FilePart from active context.
- GC may run after short grace period and may delete sooner under quota/storage pressure.
- Apply size/count budget at ModelFile creation too, so GC alone is not responsible for capacity.

### 13. Legacy payload is migration-rewritten to current schema

Existing event/native payload is migration-rewritten to current schema. Long-term compatibility is not handled only by read-time adapter and wire redaction.

Migration principles:

- Existing text `content` converts to `output` string or `text` part.
- Existing `attachments` converts to `attachment` part if retainable metadata and URI exist.
- Fields mixing file content or provider-native blob, such as existing `OutputImagePart`, `OutputFilePart`, `FunctionToolResult.images`, are not preserved.
- File-related legacy fields hard to support are removed and replaced with bounded placeholder metadata.
- inline base64, provider-specific `file_data`, provider-specific serialized payload are removed during migration.
- Migration does not create new FilePart meaning LLM can actually keep seeing file. FilePart is created only through explicit path that can create normalized blob in ModelFileStore.
- After migration, canonical read/write contract supports only current ToolResult schema.

Schema compatibility is prioritized over event immutability. ADR implementation migration exceptionally allows rewriting existing payload. Purpose of rewrite is not preserving file bytes, but removing unsafe/legacy file payload and normalizing to current schema.

### 14. Frontend wire redaction is safety net

`wire_sanitization` remains.

It protects FE payload and context inspector in these cases:

- legacy payload
- missing provider-native output shape handling
- bugs that accidentally send inline base64 to frontend payload

## Considered Options

### Option A: Separate Attachment, Artifact, FilePart

Accepted. User-agent delivery, agent/tool file output, and LLM rich input blob have different lifecycle, permission, and lowering policies, so they are separated. This choice costs schema/migration work but reduces inline base64, prompt bloat, and UI download card misuse together.

### Option B: Expand existing Attachment concept to all file resources

Rejected. If user-facing download/preview UX and internal tool output share same envelope, MCP file output or large text output appears as UI artifact and LLM lowering policy becomes ambiguous.

### Option C: Store provider-native file/image part as-is in canonical schema

Rejected. Fixing provider-specific payload shape and capability differences in canonical history makes provider migration, replay, and reduction difficult. Canonical stores provider-neutral semantic part, and native payload exists only as request-local lowering result.

### Option D: Automatically convert all non-text output into Artifact

Rejected. If FilePart intended for LLM rich input is converted to Artifact too, model capability cannot be used and user-provided file input mixes with tool-generated file output. Non-image FilePart is restricted by creation-time size cap and later placeholder/degradation on budget exceed.

### Option E: Manage Artifact by time TTL GC

Rejected. User cannot predict accessibility tied to Agent run transcript. Run-age lifecycle explains expiration by creation run and number of completed subsequent runs, and aligns deterministically with hibernate/restore.

## Consequences

Expected benefits:

- Responsibilities of Attachment, Artifact, FilePart, ModelFile are separated.
- All MCP tool file outputs become Artifact, avoiding token explosion from text file output and Attachment UX pollution.
- Attachment and Artifact lower to URI/metadata, and actual content access becomes explicit through `import_file`.
- LLM rich input is unified as FilePart and provider lowering policy can be managed in one place.
- ModelFile bytes can be separated from RDB/event payload and Exchange/Artifact lifecycle.
- Artifact expiration is fixed at run-age N=2, limiting blob accumulation.
- Frontend payload redaction remains safety net while primary design and migration remove inline base64.

Costs and risks:

- ToolResult schema, canonical output part, lowerer, tool handler interface migration is required.
- ArtifactStore, Artifact URI resolver, run-boundary artifact expiration/delete must be implemented.
- `import_file` must support both exchange and artifact resolvers.
- Introducing FilePart/ModelFileStore complicates provider lowering and reduction policy.
- Artifact expiration makes previous outputs inaccessible to agent, so lower metadata and tool error must be clear.
- Different lifecycles of Preview asset, Exchange file, Artifact file, ModelFile blob must be clearly explained in docs and UI.

## Initial Discussion Order

1. Unified ToolResult schema and canonical output part union.
2. ArtifactStore schema, `artifact://` URI, run-age N=2 expiration.
3. `import_file` resolver extension and default import directory change.
4. Attachment schema and Preview metadata.
5. FilePart schema and ModelFileStore schema.
6. Provider-specific FilePart lowering policy.
7. Reduction and FilePart degradation policy.
8. Legacy inline base64, `FunctionToolResult.images`, existing Output*Part migration.
