---
title: "Materialize Provider-Generated Images as File Resources"
created: 2026-07-17
tags: [architecture, backend, engine, frontend, llm, tools, storage, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: generated-260717
historical_reconstruction: true
migration_source: "docs/azents/adr/0164-materialize-provider-generated-images-as-file-resources.md"
---

# generated-260717/ADR: Materialize Provider-Generated Images as File Resources

## Context

The provider-hosted `image_generation` tool returns image bytes inside a provider-native response item, commonly as Base64. Azents already normalizes the provider call lifecycle, but its current image result projection creates an unavailable placeholder attachment and removes the native `result` before durable storage. The image is therefore neither downloadable by the user nor available as rich input to a later model call.

Raw image payloads cannot become canonical event data. Durable events, database rows, REST/WebSocket projections, frontend state, logs, and native artifacts must remain free of raw bytes, inline Base64, and data URLs. At the same time, a successful image-generation result has two independent consumers:

- the model needs a `FilePart` backed by a normalized ModelFile;
- the user needs an Attachment backed by an Exchange file.

The semantic behavior must be consistent across the OpenAI SDK, ChatGPT OAuth, and LiteLLM lowerers. Provider-specific response parsing and request dialect translation remain adapter-local.

## Decision

### Treat the provider payload as transient materialization input

An adapter output normalizer extracts the completed provider-native image result and converts it into a provider-neutral, in-memory pending file output. The pending output carries decoded bytes and semantic identity such as provider tool call ID, file name, and detected media type. Its byte field is excluded from serialization and representation.

The adapter also produces the canonical provider-tool result event skeleton, but that event is not eligible for durable append until all pending file outputs have been materialized.

### Persist two independent file resources from one decoded image

The shared Engine output-materialization stage uses the decoded provider bytes to prepare:

1. an Exchange file preserving the provider image for user preview and download; and
2. a ModelFile normalized through the existing model-input image policy.

The durable `provider_tool_result` references both resources:

- `output` contains a `FileOutputPart` with only `model_file_id` and bounded metadata;
- `attachments` contains an `Attachment` with only the Exchange file URI and bounded metadata.

The image body is stored only in object storage. Database rows store resource metadata and object keys. The native artifact removes `result` and all other blob-bearing fields before persistence.

### Admit file metadata and the provider result together

Provider output materialization prepares object-storage uploads before the normal model-output append transaction. The existing model-output transaction persists the prepared Exchange and ModelFile metadata before appending the provider-tool result that references them. If admission fails, uploaded objects are compensation-deleted. A completed provider-tool result is never appended with only one of the two required resources.

Invalid Base64, oversized payloads, unsupported image data, and exhausted storage failures prevent successful model-output admission. Bounded retries may reuse the same in-memory bytes for transient storage failures, but Azents does not persist the bytes as a retry payload.

### Rehydrate model input only at request time

A later model request resolves the durable `FileOutputPart` through ModelFileStore. The request-local materializer may encode the normalized image as Base64 or a data URL only inside the outbound provider request.

For a compatible Responses adapter, the lowerer may reconstruct the sanitized `image_generation_call.result` in memory. For a different adapter or provider, the lowerer emits the same FilePart through its provider-neutral rich-image fallback. Unsupported image input becomes an explicit bounded placeholder according to the existing FilePart capability policy; it is never silently omitted.

Continuation comparison uses sanitized items so request-local rehydration does not force raw image content into continuation state.

### Use capability-only builtin validation

`image_generation` validation checks only that:

- the semantic builtin is registered and implemented;
- the selected model capability advertises it;
- the selected lowerer can translate it.

There are no provider-family exclusivity rules and no Shell, reasoning, toolkit, Agent-role, or subagent constraints. Generic model-option capability validation remains the single configuration boundary.

## Consequences

- Users receive a normal downloadable Exchange attachment for every successfully admitted generated image.
- Later model calls receive the generated image through a ModelFile-backed FilePart without durable Base64.
- The Exchange image may preserve the provider format while the ModelFile follows the existing normalized model-input format and lifecycle.
- OpenAI SDK, ChatGPT OAuth, and LiteLLM share one Engine contract and differ only in request/response dialect handling.
- Output admission becomes dependent on both file stores. A storage failure is visible as run failure rather than a completed tool result with missing output.
- Resource preparation and compensation add complexity, but keep canonical history internally consistent and blob-free.

## Alternatives Considered

### Persist Base64 in the provider-tool result

Rejected because it would place large opaque bytes in the database, WebSocket/history payloads, frontend memory, compaction input, and native replay state.

### Create only an Exchange attachment

Rejected because attachments intentionally lower as metadata and do not provide rich model input.

### Create only a ModelFile

Rejected because ModelFile is an internal model-input resource without a user-facing download URI.

### Convert the Exchange attachment into a ModelFile later

Rejected because Attachment and FilePart have independent lifecycles, and Azents does not infer entity identity or model input from an Exchange URI.

### Restore the historical Gemini-specific validation rule

Rejected in favor of the current model-scoped capability contract. Provider-specific invocation limitations belong in capability projection or explicit lowerer support errors, not Agent-global configuration constraints.

## Migration provenance

- Historical source filename: `0164-materialize-provider-generated-images-as-file-resources.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
