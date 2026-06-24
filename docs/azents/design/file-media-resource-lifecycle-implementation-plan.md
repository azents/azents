---
title: "ADR-0046 file/media resource lifecycle full migration implementation plan"
created: 2026-06-02
updated: 2026-06-03
tags: [architecture, backend, frontend, engine, testing]
---

# ADR-0046 file/media resource lifecycle full migration implementation plan

## Purpose

This document is stacked implementation plan to fully apply [`ADR-0046: Attachment, Artifact, and FilePart lifecycle`](../adr/0046-file-media-resource-lifecycle.md).

Baseline document is [`ADR-0046 file/media resource lifecycle implementation audit report`](./file-media-resource-lifecycle-audit-report-2026-06-02.md), and conflict-resolution decisions finalized in the audit report's "Additional decisions" section are the implementation baseline.

As of 2026-06-03 re-audit, ADR-0046 current contract is fully implemented. This document preserves plan and phase boundaries, while current implementation status follows audit report and spec.

Final goals were following three, and all are judged complete in current stack.

- Make every ADR-0046 item fully implemented in production path.
- Remove legacy compatibility layers duplicating Attachment, Artifact, FilePart, and ModelFile.
- Ensure raw blob does not remain in canonical event, REST/WS projection, or frontend state.

## Assumptions

- Existing production event/session data migration is not performed. azents service maintains private cutover premise.
- "Migration rewrite" does not mean rewriting past data for preservation; it means current write/read path no longer creates or reads legacy shape.
- ADR-0046 body is append-only decision record. Items where body and this implementation decision conflict are corrected by ADR-0046 2026-06-03 amendment.
- `Attachment` is user-agent delivery envelope, `Artifact` is agent/tool output resource, and `FilePart` is explicit model rich input. They do not auto-convert into each other.
- Adapter-native artifact remains only as opaque replay hint, but does not take precedence over raw blob-free invariant.

## Final current contract

### URI

- URI is file-location address for bringing file into runtime or providing download link.
- Only `exchange://{object_key}` is recognized as Exchange URI.
- Only `artifact://{storage_key}` is recognized as Artifact URI.
- Entity-id URI and legacy alias such as `exchange://files/{id}`, `artifact://files/{id}`, `exchange://uploads/{id}`, `exchange://artifacts/{id}`, `artifact://{id}` are not maintained.
- To reference Entity, put entity id or entity metadata into canonical payload as separate field.
- Do not extract entity id from URI or use URI as entity reference.
- ModelFile is referenced by FilePart `model_file_id`, and ModelFile URI is not created.
- Path under scheme in every scheme is opaque file path, not routing namespace.

### Tool output part

- canonical tool output part union keeps only following four.
  - `output_text`
  - `attachment`
  - `artifact`
  - `file`
- `output_image`, `output_file`, `output_audio`, `output_video` are legacy media output parts and removed.
- MCP resource/file output is normalized to `artifact` output part.

### Attachment

- Attachment required fields are `attachment_id`, `uri`, `name`, `media_type`, `size`, `created_at`.
- Attachment optional fields include `source`, `availability`, `preview_summary`, `preview_thumbnail_uri`.
- `preview_thumbnail_uri` points to `exchange://{object_key}` file-location URI of thumbnail Exchange file, not inline base64.
- On Attachment deletion, delete attachment body and preview thumbnail Exchange file together.

### Artifact

- Artifact URI is `artifact://{storage_key}` file-location URI.
- Artifact expiration is performed during new run input preparation.
- Artifact with `expires_after_run_index < current_run_index` is expired.
- DB status update failure is run failure.
- blob delete failure is target of operational log/metric/retry, and access denial is guaranteed by DB status.

### ModelFile and FilePart

- ModelFileStore is model input blob store, not original preservation store.
- FilePart is created only by explicit action.
- Attachment/Artifact are not automatically converted to FilePart by normal tool responses such as `import_file`, `present_file`, `read_image`.
- image ModelFile is normalized to JPEG.
- non-image ModelFile is not normalized and only size cap is applied.
- If original exceeds size cap, do not create ModelFile and replace with "allowed file size exceeded" message.
- non-image ModelFile is replaced with unreachable placeholder from turn age 3 and deleted after next run boundary grace.
- Whether random/binary payload can enter model input is lowerer capability judgment. creation layer does not reject arbitrary binary based only on content.

## Stacked PR Plan

### `file-media-lifecycle [1/17]: ADR-0046 audit and decisions`

Already opened audit/decision document PR.

- Check current implementation status of each ADR-0046 item.
- List legacy layers that became duplicate concepts due to ADR.
- Record additional decisions for URI scheme, raw blob-free invariant, FilePart creation, lifecycle owner.

### `file-media-lifecycle [2/17]: implementation plan`

This document PR.

- Define implementation order, phase boundary, validation gate.
- Ensure later phases proceed from this document without missing ADR items.

### `file-media-lifecycle [3/17]: URI and schema foundations`

- Normalize Exchange/Artifact URI to be used only as file-location address.
- Remove production logic extracting entity id from URI.
- Remove legacy URI alias parsing and origin-based URI routing.
- Align needed DB column/enum/model names to current contract.
- Align OpenAPI/TypeScript client wire type with new URI contract.
- Fix existing test fixtures and stories so they do not create legacy URI.

Completion criteria:

- No production path creates `exchange://files/{id}`, `artifact://files/{id}`, `exchange://uploads/{id}`, `exchange://artifacts/{id}`, `artifact://{id}`.
- Input entity-id URI or legacy alias does not succeed and returns explicit not-found/validation error.
- URI scheme dispatch validates only file-location resolver selection, not entity id extraction.

### `file-media-lifecycle [4/17]: canonical raw-blob-free contracts`

- Reduce canonical tool output part union to `text | attachment | artifact | file`.
- Remove legacy `output_image`, `output_file`, `output_audio`, `output_video` parts.
- Remove raw blob fields from event payload, native artifact, broker payload, REST/WS projection.
- Add invariant so adapter normalizer does not store raw provider blob into canonical event.
- Remove raw blob defense code that frontend sanitization needed.

Completion criteria:

- base64/data URL blob is not stored as durable field in canonical event JSON.
- REST/WS response type does not expose raw blob field.
- Frontend has no remaining compatibility path for `raw`, `blob`, inline `base64` sanitization.

### `file-media-lifecycle [5/17]: Attachment preview and delivery envelope`

- Align Attachment payload/API required fields to current contract.
- Store Attachment preview thumbnail as Exchange file and deliver as `preview_thumbnail_uri`.
- Remove inline thumbnail/data URL field.
- Delete preview thumbnail together on Attachment deletion.
- UI attachment card resolves and renders `preview_thumbnail_uri`.

Completion criteria:

- file attachment upload, image preview, thumbnail fetch, delete flow pass E2E.
- REST history and WS streaming projection return same Attachment shape.
- UI does not break when preview thumbnail is absent.

### `file-media-lifecycle [6/17]: ArtifactStore lifecycle and MCP outputs`

- Store MCP file/resource output in ArtifactStore and return as `ArtifactOutputPart`.
- `import_file` resolver reads Artifact URI with current contract.
- Execute Artifact expiration in new run input preparation.
- Block expired Artifact access by DB status.
- blob delete failure does not fail run and remains log/metric/retry target.

Completion criteria:

- MCP resource/file output is not flattened to text marker.
- expired Artifact is inaccessible from import/download/lowering.
- DB status update failure test verifies run failure.

### `file-media-lifecycle [7/17]: ModelFileStore and explicit FilePart creation`

- Add ModelFile RDB model, repository, service, object store path.
- Make FilePart reference ModelFile entity with `model_file_id`.
- Do not create ModelFile URI.
- Normalize image ModelFile to JPEG.
- Do not normalize non-image ModelFile and apply only size cap.
- Replace oversized input with "allowed file size exceeded" message without ModelFile.
- Add explicit action converting Attachment/Artifact to FilePart.
- Ensure `import_file`, `present_file`, `read_image` do not implicitly create FilePart.

Completion criteria:

- FilePart creation path exists only in explicit action or explicit tool.
- arbitrary binary is not rejected by creation layer based only on content.
- oversized file is not stored and explicit placeholder remains for user.

### `file-media-lifecycle [8/17]: FilePart lowering, degradation, and GC`

- Apply lowerer capability matrix to FilePart.
- Use ModelFile blob only as request-local payload during model request assembly and do not store in durable event.
- image FilePart degrades to rich input, reduced representation, placeholder according to turn age policy.
- non-image FilePart is replaced with unreachable placeholder from turn age 3 and deleted after next run boundary grace.
- compaction summary keeps only file metadata and does not include blob.
- Add ModelFile GC.

Completion criteria:

- lowerer decides rich input or bounded metadata according to provider capability.
- durable transcript has no raw blob after compaction.
- turn age test verifies degrade boundary for image/non-image respectively.

### `file-media-lifecycle [9/17]: URI file-location semantics`

- Finalize Exchange/Artifact URI as storage file-location address, not entity-id reference.
- Generate only `exchange://{object_key}` and `artifact://{storage_key}`.
- Remove resolver, parser, fixture extracting file/artifact id from URI.
- ModelFile creates no URI and is referenced only by `model_file_id`.
- Align URI contract in ADR, audit report, and implementation plan documents to same decision.

Completion criteria:

- No production code path extracts entity id from URI.
- No legacy `exchange://files/{id}`, `artifact://files/{id}` creation path.
- Attachment/Artifact/FilePart fixtures use storage-location URI or explicit entity id field.

### `file-media-lifecycle [10/17]: Legacy transport and projection removal`

- Remove legacy event/WebSocket compatibility layer.
- Clean up worker, public chat API, frontend chat state to use only canonical projection.
- Remove legacy `FunctionToolResult.content/attachments` adapter path or limit it to current output part writer.
- Make input buffer, history hydration, streaming projection use only current event schema.
- Remove frontend legacy type/story/fixture.

Completion criteria:

- production path does not create or consume legacy event shape.
- old revert/legacy media transport and ADR-0046 current schema do not coexist.
- UI renders only current Attachment/Artifact/FilePart shapes.

### `file-media-lifecycle [11/17]: E2E and regression coverage`

Add E2E primary verification.

- normal text conversation
- user attachment upload and history reload
- attachment preview thumbnail rendering
- explicit FilePart creation
- image FilePart rich input lowering
- non-image FilePart size cap and turn age 3 removal
- MCP file/resource output Artifact creation
- Artifact expiration after run boundary
- `import_file` with Exchange/Artifact URI
- raw blob-free durable transcript after compaction
- legacy URI rejection
- REST/WS projection raw blob absence

Also reinforce unit/integration tests.

- URI scheme dispatch without entity-id extraction
- output part validation
- Attachment required field validation
- Artifact expiration failure semantics
- ModelFile normalization/size cap
- lowerer capability branch
- raw blob invariant guard

Completion criteria:

- local E2E and CI E2E verify same primary behavior.
- Tests requiring live provider credential clearly state skip condition and evidence.

### `file-media-lifecycle [12/17]: ModelFile reduction lifecycle`

- Align ModelFile reduction lifecycle to ADR-0046 policy.
- image ModelFile degrades to max edge 1024 JPEG at age 1.
- image ModelFile degrades to max edge 300 JPEG at age 3.
- image ModelFile becomes unreachable at age 10+ and tries blob delete after next run boundary grace.
- non-image ModelFile becomes unreachable at age 3+ and tries blob delete after next run boundary grace.
- degraded ModelFile must remain downloadable for rich input lowering.
- deleted/unreachable ModelFile is treated as unavailable.
- Remove old direct retention delete shortcut and replace with explicit lifecycle transition.

Completion criteria:

- ModelFile service/repository unit tests verify normalize, size cap, degrade, unreachable, deleted transition.
- ModelFile lifecycle hook is called during run input preparation.
- No ModelFile URI is created and only FilePart `model_file_id` is used.

### `file-media-lifecycle [13/17]: Final audit, spec promotion, and cleanup`

- Update `docs/azents/spec/` to current implementation.
- Update `code_paths` and `last_verified_at` for specs related to file/media resource lifecycle, tool output shape, chat projection, agent execution lowering.
- Add new ADR if ADR-0046 and later decisions require append-only record.
- Update audit report to current stacked head.
- Remove remaining legacy compatibility layer from production path or mark as item tied to ADR-0039 cleanup.
- After implementation completion, remove temporary implementation plan document or organize separately as completed-state document.

Completion criteria:

- `/spec-review` finds no missing spec drift related to file/media lifecycle.
- No different current contract between implementation plan and spec.
- Audit report accurately reveals remaining gaps in current implementation.
- docs index, Python quality, TypeScript quality, E2E pass.

### `file-media-lifecycle [14/17]: Canonical user input boundary cleanup`

- Change `RunRequest.user_messages` from legacy `Event(UserInputEvent)` to canonical `RunUserMessage`.
- Worker direct message path passes canonical `UserMessagePayload` based input without creating `UserInputEvent`.
- input buffer promotion appends directly to canonical transcript without going through legacy event store.
- In-run polled follow-up message also converts to canonical input.
- batch service invoke does not pre-append user input to legacy event store.
- Replace adapter legacy `_append_user_messages()` conversion boundary with canonical append helper.

Completion criteria:

- Production paths in `python/apps/azents/src/azents/worker/engine.py`,
  `python/apps/azents/src/azents/engine/run/resolve.py`,
  `python/apps/azents/src/azents/services/input_buffer_promotion.py`,
  `python/apps/azents/src/azents/runtime/canonical/engine_adapter.py`
  do not create or consume `UserInputEvent`.
- After input buffer flush, REST history and WebSocket durable publish operate based on canonical `user_message`.
- direct input, queued follow-up, background completion input all append to canonical transcript as `RunUserMessage`.
- Related unit tests, pyright, deterministic input buffer E2E pass.

### `file-media-lifecycle [15/17]: Frontend canonical chat events`

- Remove legacy durable item payload from frontend chat event union.
- Remove `UserInputEvent`, `ToolCallOutputItemEvent`, `ImageGenerationItemPayload`, legacy `images` wire field.
- chat WebSocket hook handles durable user/assistant/tool/file/media state only as canonical `kind/payload` event.
- subagent live hook also handles canonical durable event and limits `type` based path to streaming delta/control event.
- Narrow events at JSON parse boundary with discriminator guard instead of type assertion.

Completion criteria:

- Production code in `typescript/apps/azents-web/src/features/chat` does not import or switch legacy durable file/media event type.
- frontend state renders only canonical Attachment/Artifact/FilePart current shape.
- `pnpm --filter @azents/web typecheck` and `pnpm --filter @azents/web lint` pass.

### `file-media-lifecycle [16/17]: Runtime legacy event module cleanup`

- Remove legacy `Event` support from canonical engine/broker production path.
- Clean legacy durable event classifier/store/context helpers around canonical runtime events.
- Convert remaining legacy durable envelope such as user-visible error, subagent start/end, compaction marker to canonical event or explicit control event.
- broker serialization serializes only canonical event and explicit stream/control event.

Completion criteria:

- production path does not create legacy `Event` as durable transcript or broker payload.
- After legacy module deletion or test-only isolation, there is no production import.
- public chat REST/WS projection returns only canonical event or explicit control event.

### `file-media-lifecycle [17/17]: FilePart placeholder rewrite and final verification`

- pre-lower/reduction pass replaces unavailable/deleted ModelFile FilePart with bounded metadata placeholder.
- active transcript FilePart payload no longer keeps inaccessible blob identity as rich input.
- Add dedicated test so compaction summary contains only bounded metadata, not FilePart blob or provider payload.
- Update final audit report against current implementation status and clean implementation plan/spec drift.

Completion criteria:

- ADR-0046 audit report reveals every remaining gap in current implementation.
- If not every item is `[x] fully applied`, specify `[~]`, `[ ]`, `[!]` status and follow-up implementation needs.
- Unit/integration test exists that deleted/unavailable ModelFile FilePart lowers to placeholder in model request.
- compaction summary raw blob-free regression test exists.
- Python/TypeScript quality and related E2E pass.

No implementation items remain in current re-audit.
- test evidence directly verifying compaction summary raw blob-free requirement in ADR 12 scope.

## Test Strategy

Product behavior verification is E2E primary. Unit/integration tests are used to fix invariants whose failure cause is hard to narrow with E2E alone, such as schema, lifecycle, lowerer branch.

E2E primary verification plan:

- Send text message in chat page and verify user/assistant events are restored from durable transcript after reload.
- Upload image attachment and verify preview thumbnail is visible through `exchange://{object_key}` resolver.
- Upload non-image attachment and verify it remains metadata delivery envelope, not model rich input.
- Run explicit FilePart creation action and verify rich input or metadata lowering works according to capability in next model call.
- When MCP tool returns file/resource output, verify chat UI displays Artifact part and `import_file` reads `artifact://{storage_key}`.
- Verify expired artifact access is denied after run index increases.
- Verify no raw blob/data URL exists in event payload, REST response, WS projection after compaction.
- Verify legacy URI input returns validation error without silent fallback.

testenv support when needed:

- rich file lowering requiring provider live behavior is skipped when credentials absent.
- Fault injection such as object store failure, DB update failure, artifact blob delete retry is supplemented by testenv fixture or integration test.
- Credential snapshot stores only provider name, model name, capability flag and does not store token/provider trace.

CI policy:

- Each phase PR must pass language quality checks and related unit/integration tests.
- Full E2E matrix is enabled at phase 10, but phase 3-9 also run directly related smoke E2E locally and leave evidence in PR body.
- optional/live provider test is skipped without credential; provider 4xx with credential is failure.

## Risks and Responses

- URI scheme cleanup and legacy alias removal can break frontend/backend/test fixture simultaneously. Fix parser/formatter first in phase 3, and later phases use formatter only.
- raw blob-free invariant spans adapter, REST, WS, and frontend state boundaries. Add invariant guard in phase 4 to catch regressions in later phases early.
- ModelFileStore is new durable resource. Finish service/repository/test narrowly in phase 7 and separate lowerer use into phase 8.
- Artifact expiration depends on run boundary and transaction semantics. In phase 6, test DB status update failure and blob delete failure as different failure grades.
- legacy transport removal has high UI regression risk. Phase 10 E2E draft can be prepared before phase 9, but merge order stays after current contract stabilizes.
