---
title: "Use Single Durable Events for Provider Tool Items"
created: 2026-07-19
tags: [architecture, backend, engine, frontend, llm, tools, storage, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: events-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0168-use-single-provider-tool-events.md"
---

# events-260719/ADR: Use Single Durable Events for Provider Tool Items

## Status

Accepted during design discussion. Not yet implemented.

## Context

[semantic-260718/ADR](./semantic-260718-semantic-transcript.md) introduced a shared provider-neutral `ProviderToolSemanticContent` contract for provider-hosted tools while retaining both `provider_tool_call` and `provider_tool_result` event kinds. That contract correctly allows a single native hosted-tool item to carry both semantic input and output, but the initial implementation still classifies OpenAI Responses `image_generation_call` as `provider_tool_result`.

This leaves one native provider item represented through a special result event even though other hosted-tool output items, including Web search, file search, code interpreter, and MCP calls, are represented as `provider_tool_call`. It also keeps provider result handling, frontend call/result merging, and separate tool-level `attachments` fields solely for generated-image delivery.

The distinction does not reflect provider execution ownership. Provider-hosted tools execute entirely inside the provider response. Unlike Azents client tools, they do not require a durable request event followed by a separately executed result event. A native item such as `image_generation_call` already contains its lifecycle state and provider result.

[generated-260717/ADR](./generated-260717-generated-images-as-file-resources.md) remains correct that a successful generated image requires two independently stored resources:

- a ModelFile-backed `FileOutputPart` for later model input; and
- an Exchange-backed attachment for user delivery.

The question is how those references are represented in the durable event transcript, not whether both resources exist.

## Decision

### Store each provider-hosted native item as one `provider_tool_call`

Every recognized durable provider-hosted tool output item produces exactly one `provider_tool_call` event. The event owns:

- provider tool identity and lifecycle status;
- provider-neutral semantic input, output, and references;
- the compatible native artifact used for same-native replay.

`image_generation_call` is normalized as `provider_tool_call`, like every other currently recognized Responses hosted-tool item. Its materialized generated-file references are added to that event's semantic output before durable admission.

Remove `provider_tool_result`, `ProviderToolResultPayload`, and the corresponding public/frontend event variant. Provider result content remains representable because `ProviderToolCallPayload.semantic.output` already uses the shared `ToolOutput` contract.

This decision supersedes [semantic-260718/ADR-D2](./semantic-260718-semantic-transcript.md) only where it retains a separate provider result event kind. [semantic-260718/ADR](./semantic-260718-semantic-transcript.md)'s adapter-owned semantic extraction, bounding, references, and strict native-artifact rules remain in force.

### Make tool output the canonical attachment delivery location

Tool-created user-delivery files are represented by `AttachmentOutputPart` inside the owning tool output:

- provider-hosted tool files use `ProviderToolCallPayload.semantic.output`;
- client-executed tool files use `ClientToolResultPayload.output`.

Generated images therefore use the following durable output shape:

```text
output
  FileOutputPart
  AttachmentOutputPart
```

Remove tool-level `attachments` fields from provider tool calls and client tool results. User and assistant message attachments remain payload-specific fields because they represent message delivery rather than tool output.

This changes only the event reference location from [generated-260717/ADR](./generated-260717-generated-images-as-file-resources.md). Exchange and ModelFile storage identities, authorization, lifecycle, and atomic admission remain independent.

### Allow one durable event to lower to multiple native input items

A durable event is not required to map one-to-one to provider request items.

For compatible same-native image replay:

1. the lowerer combines the sanitized native artifact with the event's `FileOutputPart` to reconstruct the request-local native image result;
2. that FileOutputPart is marked consumed by native reconstruction;
3. provider semantic input and references represented by the compatible native item are not rendered again;
4. unconsumed Azents-local output, including `AttachmentOutputPart`, is lowered as a bounded user-compatible provider-tool context item.

For cross-native lowering, the semantic input, FileOutputPart, AttachmentOutputPart, and references are lowered through the target adapter's provider-neutral fallback. Adapter wire roles are not stored in the durable event.

A part consumed by native reconstruction is not emitted again by generic semantic lowering. This prevents duplicate image input while keeping the Exchange URI model-visible.

### Present one provider tool card

Live provider-tool activity and the final durable provider tool event use the same semantic `call_id`. The frontend replaces the running projection with the durable call event and renders one provider tool card.

- `OutputTextPart` is rendered as tool output detail.
- `AttachmentOutputPart` is projected as a downloadable card attachment.
- `FileOutputPart` remains model-input-only and is not rendered as a second user-visible file.
- Image-generation attachments remain directly visible in the card.
- No assistant attachment bubble or separate provider-result merge is created.

## Data Migration

Do not modify migration `25bc37eadace`, which may already have executed. Add a new migration that:

1. rewrites every `provider_tool_result` row to `provider_tool_call`;
2. preserves call identity, semantic input/output/references, lifecycle status, native artifact, and event ordering;
3. converts each tool-level Attachment snapshot into an `AttachmentOutputPart` appended to semantic output;
4. converts client-tool result attachments into `AttachmentOutputPart` values appended to client output;
5. removes migrated `attachments` keys from tool payload JSON;
6. replaces the PostgreSQL `event_kind` enum after all rows are rewritten so `provider_tool_result` can be removed safely.

Provider tool status becomes one provider-neutral nullable lifecycle vocabulary capable of preserving running and terminal states. Runtime payload models do not provide legacy parsing fallbacks after migration.

## Consequences

- Provider-hosted transcript shape matches provider execution ownership: one native item, one durable event.
- Generated-image ModelFile replay no longer depends on another event or call/result pairing.
- Exchange attachment URI visibility is derived from the same durable event without placing Azents fields inside provider-native schemas.
- Frontend call/result merge state and provider-result fallback handling are removed.
- Tool output has one canonical structured-content location.
- Same-native lowerers must support zero-to-many request items per durable event and explicit consumed-part tracking.
- A new data migration and API/client type regeneration are required.
- Existing implemented ADRs remain immutable; this ADR records the replacement decision.

## Alternatives Considered

### Keep provider call and result events and pair them during lowering

Rejected because native replay would require cross-event correlation, adjacency rules, and failure handling for orphaned pairs even though the provider emitted one item.

### Keep the ModelFile on a call event and append a separate attachment result event

Rejected because the attachment context can be derived from an output part in the same event. A second durable event adds ordering, UI grouping, and compaction complexity without adding a distinct lifecycle owner.

### Keep `provider_tool_result` only for image generation

Rejected because it preserves a special event kind and frontend merge path for the only current producer. `ProviderToolSemanticContent` already supports output on call events.

### Keep attachments outside ToolOutput

Rejected because every model, UI, emit, compaction, and availability consumer must then merge two content locations and deduplicate them. `AttachmentOutputPart` already provides the required bounded durable contract.

## Related Decisions

- [execution-260527/ADR: Agent Execution Transcript Normalization](./execution-260527-execution-transcript-normalization.md)
- [file-260601/ADR: File and Media Resource Lifecycle](./file-260601-file-media-resource-lifecycle.md)
- [event-260613/ADR: Event and Native Event Terminology](./event-260613-event-event-terminology.md)
- [generated-260717/ADR: Materialize Provider-Generated Images as File Resources](./generated-260717-generated-images-as-file-resources.md)
- [semantic-260718/ADR: Normalize Provider Tool Semantic Transcript Content](./semantic-260718-semantic-transcript.md)

## Migration provenance

- Historical source filename: `0168-use-single-provider-tool-events.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
