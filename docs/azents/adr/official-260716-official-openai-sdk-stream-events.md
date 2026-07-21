---
title: "Use Official OpenAI SDK Native Stream Events"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, streaming, typing, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: official-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0153-use-official-openai-sdk-native-stream-events.md"
---

# official-260716/ADR: Use Official OpenAI SDK Native Stream Events

## Status

Accepted. Implementation has not started.

## Context

[generic-260716/ADR](./generic-260716-generic-adapter-request-types.md) restores the generic native adapter pipeline. The official OpenAI SDK already parses Responses HTTP streams into the typed `ResponseStreamEvent` union, including typed response, output item, usage, error, and delta fields.

Introducing an Azents-owned dictionary event wrapper between the SDK adapter and the output normalizer would discard useful type information and duplicate part of the SDK contract. The required compatibility property is semantic native-event round-trip: completed native output items and provider extension fields must survive serialization into sanitized durable native artifacts and replay through the matching lowerer. Byte-for-byte HTTP or SSE frame preservation is not required by [http-260716/ADR](./http-260716-openai-http-migration-by-semantic-parity.md).

The SDK may loosely construct a known event class for a wire discriminator unknown to the installed SDK version. This is an intentional forward-compatible fallback: the original `type` value and extra fields remain available on the model. Azents does not need to replace the typed event model to accommodate that fallback.

## Decision

### Pass official SDK event objects directly

The OpenAI HTTP adapter yields the official SDK `ResponseStreamEvent` union directly. The generic adapter boundary uses the SDK event type as `TNativeStreamEvent`, and the OpenAI output normalizer consumes the same typed event objects.

Azents does not introduce a dictionary-only `OpenAIResponsesEvent` wrapper and does not eagerly call `model_dump()` merely to cross the adapter boundary.

Known events are normalized through their official SDK classes and typed fields. Terminal success and failure, text and reasoning deltas, function-call deltas, completed output items, response usage, and provider error details retain their SDK types until a serialization boundary is reached.

### Accept the SDK unknown-event fallback

An event discriminator unknown to the pinned SDK may be represented by a loosely constructed known class. Azents accepts that SDK behavior rather than enabling strict response validation or failing the model call.

Normalization promotes only explicitly supported event variants. When a handler is added for an event class, its documented wire `type` literal is part of the handler condition so an unknown discriminator carried by an incidental fallback class is not promoted as the known event. Unsupported events remain non-terminal and do not create an incorrect live projection or canonical event.

This defensive condition does not replace SDK typing with dictionary dispatch. It only preserves the distinction between a supported SDK variant and the SDK's forward-compatible unknown fallback.

### Serialize native data only where required

SDK models are serialized only when a plain data representation is required, including durable native artifacts, copied cost-calculation input, and deterministic fixtures.

Native artifact serialization uses Pydantic round-trip serialization with unset fields excluded while preserving explicitly supplied null values and extra provider fields. This prevents loose fallback classes from injecting absent default fields while retaining the original wire discriminator and provider extensions. Existing raw-blob sanitization runs after serialization.

The durable artifact remains plain sanitized data; Python SDK objects are not persisted. Replaying a compatible artifact validates or lowers that data into the official OpenAI Responses input parameter types.

## Consequences

- The normalizer retains the SDK's static types for nested responses, output items, usage, errors, and deltas.
- Known event handling does not duplicate SDK payload parsing through broad dictionary access.
- OpenAI and ChatGPT OAuth extension fields preserved by SDK models survive native artifact serialization.
- Unknown SDK event fallbacks remain forward compatible without being promoted as supported variants.
- Semantic native-event round-trip is testable with known events, explicit nulls, extra fields, and an unknown discriminator fixture.
- Exact raw SSE bytes, field ordering, and transport frames are not persisted or logged.

## Alternatives Considered

### Convert SDK events into an Azents-owned dictionary wrapper

Rejected because it discards useful SDK type information without improving the required semantic native-event round-trip.

### Enable strict SDK response validation

Rejected because OpenAI version skew or ChatGPT OAuth Responses Lite extensions could turn a forward-compatible unknown event into a failed model call.

### Persist SDK Python objects

Rejected because durable transcript data must remain language- and SDK-object-independent plain data with explicit sanitization.

## Migration provenance

- Historical source filename: `0153-use-official-openai-sdk-native-stream-events.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
