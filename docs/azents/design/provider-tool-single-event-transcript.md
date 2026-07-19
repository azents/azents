---
title: "Provider Tool Single-Event Transcript Design"
created: 2026-07-19
updated: 2026-07-19
implemented: 2026-07-19
tags: [backend, engine, frontend, llm, tools, storage]
---

# Provider Tool Single-Event Transcript Design

## Problem

The provider-tool semantic transcript implemented on 2026-07-18 normalizes provider-exposed input, output, and references into a shared `ProviderToolSemanticContent` contract. It still retains `provider_tool_call` and `provider_tool_result` event kinds, and currently classifies `image_generation_call` as the only produced provider result event.

Generated images also use two canonical content locations:

- `semantic.output` contains the ModelFile-backed FileOutputPart;
- `attachments` contains the Exchange-backed user-delivery Attachment.

This produces several unnecessary branches:

- image generation differs from every other recognized hosted-tool item;
- same-native image replay is implemented only for provider result payloads;
- frontend state merges provider result output into a provider call card by call ID;
- emit, compaction, context inspection, file availability, and model-file consumers support both provider call and result payloads;
- attachment consumers merge structured output and a separate attachments list.

The provider emitted one `image_generation_call` item. The durable transcript should not invent a second lifecycle boundary or a special result event merely because the native item contains a result.

## Goals

- Represent each provider-hosted native item as exactly one durable provider tool event.
- Keep generated image ModelFile and Exchange attachment references on that event.
- Make Exchange attachment URI visible to later model turns without adding fields to provider-native schemas.
- Preserve strict same-native replay and provider-neutral cross-native lowering.
- Use ToolOutput as the canonical location for tool-created attachments.
- Render one provider tool card without call/result merge state.
- Preserve blob-free event, API, frontend, log, and native-artifact boundaries.

## Non-goals

- Combine client tool calls and results; Azents executes client tools and retains separate lifecycle ownership.
- Change Exchange or ModelFile storage identity, retention, authorization, or normalization.
- Infer ModelFile identity from Exchange URI or vice versa.
- Persist raw provider image bytes, Base64, data URLs, or request-local rehydrated payloads.
- Add legacy runtime parsing after the migration cutover.
- Modify migration `25bc37eadace`.

## Current Behavior

```text
image_generation_call native item
  -> provider_tool_result event
       semantic.output
         FileOutputPart
       attachments
         Attachment
       native_artifact
```

The compatible Responses lowerer rehydrates `image_generation_call.result` only from `ProviderToolResultPayload`. Canonical fallback lowering renders provider semantic content. The frontend receives a provider result event and merges its status, text, and attachments into a provider call card by `call_id`.

Other recognized hosted-tool output items already normalize to `provider_tool_call`, and ADR-0167 allows those call events to contain semantic output.

## Proposed Durable Contract

### Provider tool event

Remove `ProviderToolResultPayload` and use one payload for all provider-hosted items:

```text
ProviderToolCallPayload
  call_id: string
  name: string
  status: running | completed | failed | cancelled | interrupted | null
  semantic:
    input: string | null
    output: ToolOutput
    references: ProviderToolReference[]
  native_artifact: NativeArtifact
```

`ProviderToolCallPayload` has no separate `attachments` field. User-delivery tool attachments are `AttachmentOutputPart` values in `semantic.output`.

The `provider_tool_result` EventKind, payload model, event union variant, API schema variant, generated client types, compaction branch, context-inspector branch, message projection branch, and frontend reducer branch are removed.

### Client tool result

Keep the client tool call/result lifecycle because Azents owns client execution. Canonicalize client result delivery into output:

```text
ClientToolResultPayload
  call_id
  name
  status
  output:
    OutputTextPart | FileOutputPart | AttachmentOutputPart | ArtifactOutputPart
  metadata
```

Remove `ClientToolResultPayload.attachments`. Existing tools such as `present_file` already use AttachmentOutputPart. xAI Imagine generated results change from FileOutputPart plus a separate attachments list to FileOutputPart plus AttachmentOutputPart in output.

UserMessagePayload and AssistantMessagePayload retain their payload-specific attachments fields.

## Generated Image Admission

Provider and client generated images continue to use the shared generated-file materializer.

For provider-hosted image generation:

1. the adapter recognizes one completed `image_generation_call` and emits a provider call event skeleton plus transient pending bytes;
2. the materializer validates and stores the Exchange original and normalized ModelFile;
3. it replaces the call event's semantic output with a FileOutputPart and AttachmentOutputPart;
4. file metadata and the single provider call event are admitted atomically.

For client-executed image generation, the same two output parts are attached to the existing client tool result.

No successful durable generated-image event may reference only one resource.

## Lowering

### Lowering result cardinality

Change event lowering from zero-or-one native input item to zero-or-many items. The request builder flattens the items returned for each durable event while preserving event order and per-event item order.

This is an adapter implementation detail. Durable events do not store wire roles or synthetic request-item identities.

### Compatible same-native image replay

For a compatible image-generation provider call:

1. resolve the FileOutputPart through the request-local ModelFile resolver;
2. reconstruct the sanitized native `image_generation_call` with request-local result bytes;
3. mark that FileOutputPart consumed;
4. lower the remaining semantic content as a bounded user-compatible provider-tool context item.

For a compatible artifact, semantic input and references are already represented by the native item and are not rendered again. The remaining context contains only Azents-local output that the native schema cannot represent, currently the AttachmentOutputPart. Its context text includes the generated attachment name, media type, bounded size metadata, and `exchange://` URI.

The rehydrated native item and synthetic context are outbound request objects only. Neither is persisted.

### Cross-native lowering

When the native artifact is incompatible, lower the provider tool semantic input, unconsumed output parts, and references through the target adapter's generic provider-tool fallback.

- FileOutputPart becomes rich image input when supported or the normal bounded unavailable-file placeholder.
- AttachmentOutputPart becomes bounded attachment metadata text containing the Exchange URI.
- References use the shared provider-tool renderer.
- Provider-native dictionaries are not inspected.

### Consumed output parts

A lowerer records which output parts were used to reconstruct a native item. Generic semantic lowering receives only unconsumed parts. This prevents the generated image from appearing once as a native result and again as rich image input.

AttachmentOutputPart is not consumed by native image reconstruction because the provider-native item has no Azents Exchange URI field.

## Compaction and Context Inspection

Compaction, continuity rendering, token estimation, context inspection, and fork context consume only `ProviderToolCallPayload.semantic`.

Tool attachment metadata is read from ToolOutput like every other structured tool part. Consumers do not inspect separate attachments fields or provider native artifacts.

The token estimate counts the bounded model-visible rendering of AttachmentOutputPart, not storage metadata or raw file contents.

## UI and Projection

### Backend projection

A provider call message projection contains:

- call ID, name, arguments/semantic input, and status;
- readable OutputTextPart content;
- attachments derived from AttachmentOutputPart;
- no user-facing projection for FileOutputPart.

Run terminal-result collection and attachment emit use the same output-part traversal.

### Frontend state

The live provider-tool call and durable provider-tool event share a semantic call ID.

- A running live event creates or updates one ProviderToolCallCard.
- The final durable event replaces it with completed status and output.
- No provider result reducer or call/result merge function remains.
- Image-generation attachments render directly in the tool card.
- Other provider tool attachments may remain inside the card detail surface.
- No duplicate assistant attachment bubble is created.

History reload, live-to-durable handoff, and resync must produce the same one-card projection.

## Error Handling

- Missing provider tool identity remains `unknown_adapter_output`.
- Invalid or oversized generated bytes fail output admission before the durable provider call is appended.
- Exchange or ModelFile persistence failure fails the model output and compensation-deletes unowned objects.
- Missing request-local ModelFile content uses the existing explicit unavailable-file behavior; it does not silently remove the result.
- Attachment availability filters rewrite or mark AttachmentOutputPart using the same lifecycle rules as existing attachment snapshots.
- A malformed migrated event fails canonical validation rather than entering a runtime legacy fallback.

## Security and Privacy

- Native artifacts remain sanitized and opaque outside their adapter.
- Durable events, API responses, WebSocket messages, frontend state, logs, compaction input, and context inspection contain no image Base64, raw bytes, data URLs, credentials, headers, cookies, or raw provider bodies.
- Exchange URIs remain authorization-gated file-location references.
- Synthetic attachment context contains bounded metadata only.
- Provider semantic extraction remains allowlisted and bounded under ADR-0167.

## Migration and Rollout

Migration `25bc37eadace` is immutable and remains the historical semantic-contract migration. Generate a new Alembic revision after it.

The new migration performs an atomic clean cutover:

1. convert provider tool result payload attachments into AttachmentOutputPart values appended to `semantic.output`;
2. change all provider tool result rows to provider tool call rows while preserving IDs, model order, provider provenance, native format, schema version, and external IDs;
3. convert provider tool call attachments into output parts and remove the attachments key;
4. convert client tool result attachments into output parts and remove the attachments key;
5. replace the PostgreSQL event_kind enum without `provider_tool_result` after no row uses it;
6. update the schema revision pointer.

The runtime, OpenAPI schema, generated clients, and frontend cut over in the same release. There is no feature flag, dual-write period, or legacy parser.

## Implementation Phases

### Phase 1: Event contract and migration

- Generate the follow-up Alembic revision.
- Rewrite current event rows and replace the enum.
- Remove ProviderToolResultPayload and tool-level attachments fields.
- Update payload validation, serialization, model-file references, attachment availability, compaction, continuity, context inspection, and emit consumers.
- Normalize every Responses hosted-tool item, including image generation, as provider_tool_call.

### Phase 2: Lowerers

- Change lowerer cardinality to zero-to-many native items.
- Rehydrate image generation from provider call semantic output.
- Add consumed-part filtering.
- Emit user-compatible AttachmentOutputPart context for same-native replay.
- Preserve provider-neutral rich-file and attachment fallback across every supported lowerer.

### Phase 3: API and frontend

- Regenerate OpenAPI clients after the event union changes.
- Remove provider_tool_result frontend types and reducers.
- Project output-part attachments directly onto provider tool cards.
- Verify live-to-durable replacement, reload, resync, and attachment download.
- Update Storybook provider tool call fixtures for running, completed image, failed, and generic attachment states.

### Phase 4: Spec and QA

- Update conversation, agent execution loop, file exchange storage, context compaction, context inspector, and chat resync specs.
- Run spec review after implementation phases are integrated.
- Execute full backend and frontend quality checks and deterministic E2E validation.

## Test Strategy

### Unit and contract matrix

| Area | Required cases |
| --- | --- |
| Event schema | provider_tool_result is absent; provider call accepts semantic output; tool attachments exist only as output parts |
| Provider registry | image_generation_call normalizes to provider_tool_call |
| Materialization | provider and client generated images produce FileOutputPart plus AttachmentOutputPart atomically |
| Native replay | compatible call reconstructs one native image result and one attachment URI context item |
| Deduplication | the consumed FileOutputPart is not emitted as a second rich image input |
| Cross-native replay | rich image and Exchange URI both reach the target request through generic lowering |
| Availability | expired/missing ModelFile and Exchange attachment follow their independent placeholder/availability rules |
| Compaction | provider semantic input, output, references, and bounded attachment URI survive; native artifact does not render |
| Context inspection | model-visible estimate matches lowerer-visible semantic content |
| Emit | terminal run result collects one generated attachment from output parts |
| Migration | provider result rows become calls, attachments become output parts, and event enum drops result kind |
| Public API | event union and generated clients contain no provider_tool_result variant |
| Frontend | live and durable call converge into one card with one image attachment |

### E2E primary validation

Use the deterministic OpenAI-compatible provider image fixture and request capture.

1. Run an Agent turn that invokes provider-hosted image generation.
2. Assert durable history contains one completed provider_tool_call for image_generation.
3. Assert its semantic output contains exactly one FileOutputPart and one AttachmentOutputPart.
4. Assert event JSON, native artifact, REST/WS payloads, and frontend state contain no Base64 or data URL.
5. Assert the chat renders one provider tool card and one downloadable image attachment.
6. Continue with the same native target and assert the captured request contains one rehydrated image_generation_call plus one bounded Exchange URI context item.
7. Continue with an incompatible target and assert the captured request contains one rich image fallback plus the same Exchange URI context.
8. Force compaction and verify the bounded attachment metadata remains model-visible without raw native payloads.

Add a client-executed xAI fixture case proving the same FileOutputPart plus AttachmentOutputPart contract on ClientToolResultPayload.

### Fixture and evidence policy

- Deterministic fixtures are required and CI-blocking.
- No live provider credential is required for primary verification.
- Optional live OpenAI or xAI runs are diagnostic only and skip when credentials, entitlement, or provider availability is absent.
- Fixture snapshots must contain bounded synthetic image bytes and request summaries, never secrets or full production-sized payloads.
- Evidence includes Ruff, Pyright, full relevant Pytest, migration upgrade/downgrade tests, generated-client diff validation, TypeScript format/lint/typecheck/build, Storybook state coverage, and E2E request captures.

## Alternatives

### Separate provider call and result events

Rejected because it requires cross-event pairing for a provider item that is already complete.

### One provider call plus a separate attachment delivery event

Rejected because AttachmentOutputPart provides the delivery contract without another durable lifecycle or ordering unit.

### Keep provider result only for image generation

Rejected because it preserves a special event kind and frontend merge path for the only current producer.

### Preserve separate tool attachments fields

Rejected because it leaves two canonical content locations and forces every consumer to merge and deduplicate them.

## Required Spec Updates

- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/file-exchange-storage.md`
- `docs/azents/spec/flow/context-compaction.md`
- `docs/azents/spec/flow/session-context-inspector.md`
- `docs/azents/spec/flow/chat-session-resync.md`

## Related Decisions

- [ADR-0164: Materialize Provider-Generated Images as File Resources](../adr/0164-materialize-provider-generated-images-as-file-resources.md)
- [ADR-0167: Normalize Provider Tool Semantic Transcript Content](../adr/0167-normalize-provider-tool-semantic-transcript.md)
- [ADR-0168: Use Single Durable Events for Provider Tool Items](../adr/0168-use-single-provider-tool-events.md)
