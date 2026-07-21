---
title: "Use Generic Native Adapter Request Types"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, typing, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: generic-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0151-use-generic-native-adapter-request-types.md"
---

# generic-260716/ADR: Use Generic Native Adapter Request Types

## Status

Accepted. Implementation has not started.

## Context

[execution-260527/ADR](./execution-260527-execution-transcript-normalization.md) designed the model adapter boundary as generic over each adapter's native request and stream event types:

- `AdapterLowerer[TNativeRequest]`;
- `PostLowerFilter[TNativeRequest]`;
- `ModelAdapter[TNativeRequest, TNativeStreamEvent]`;
- `AdapterOutputNormalizer[TNativeStreamEvent]`.

The first implementation collapsed that design into one non-generic `NativeModelRequest` with `model`, dictionary-based `input` and `tools`, and an untyped `kwargs` bag. This reduced the initial implementation surface while LiteLLM Responses was the only transport family, but it mixed logical request parameters, provider routing data, client credentials, and transport options in one object.

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-106) introduces an OpenAI-native Responses transport family, and [http-260716/ADR](./http-260716-openai-http-migration-by-semantic-parity.md) requires semantic request parity across primary sampling, compaction, and automatic Session title generation. Reusing the untyped request bag would make the OpenAI HTTP and later WebSocket transports depend on implicit dictionary conventions rather than one enforceable request contract.

## Decision

### Restore the generic adapter pipeline

Parameterize the adapter pipeline over the entire adapter-native request type and native stream event type. The generic boundary applies to the lowerer, post-lower filters, model adapter, output normalizer, prepared model call, and the execution path that connects them.

The pipeline does not require every provider request to inherit from one field-based base model. Shared operations use narrow structural protocols or adapter-specific filters instead of assuming a universal `input`, `tools`, and `kwargs` layout.

### Use provider-specific immutable request types

The OpenAI-native path uses an Azents-owned immutable `OpenAIResponsesRequest`. It exposes the supported logical OpenAI Responses request fields explicitly and uses official OpenAI parameter types where appropriate for input items, tools, reasoning, text configuration, include values, and other request body fields.

The OpenAI request type excludes client and physical transport state:

- API keys, base URLs, and default headers belong to separately injected OpenAI client configuration;
- connect and stream deadlines remain owned by `ModelStreamWatchdog` and the transport call;
- `stream=true`, incremental physical input, and `previous_response_id` are produced by the adapter's dispatch plan;
- an eventual HTTP or WebSocket envelope does not change the canonical OpenAI request.

Primary Agent sampling obtains `OpenAIResponsesRequest` through `OpenAIResponsesLowerer`. OpenAI compaction and Session title helpers construct the same request type from their already prepared input rather than routing synthetic input through the event-transcript lowerer.

The LiteLLM path uses its own request type. It may retain dictionary-based provider extensions where LiteLLM's multi-provider surface requires them, without weakening the OpenAI request contract.

### Keep request guards generic without reintroducing an untyped envelope

`NativeRequestSizeGuard` and other shared post-lower behavior operate through a narrow request-inspection protocol or provider-specific `PostLowerFilter[TNativeRequest]`. They evaluate the complete logical provider request before continuation or transport-specific reduction and do not include credentials or connection settings.

## Consequences

- OpenAI HTTP and later WebSocket transports consume the same statically identifiable logical request.
- Unsupported or misplaced OpenAI options can fail at the lowering/request-construction boundary instead of surviving in an untyped `kwargs` bag.
- Continuation equality and request-size enforcement compare logical request semantics rather than credentials or physical transport state.
- LiteLLM remains free to represent provider-specific extensions without making every adapter use its least-specific dictionary contract.
- Restoring generics affects several internal protocols and execution types, increasing the first HTTP migration phase's refactoring scope.
- OpenAI SDK type upgrades can affect the OpenAI-specific request boundary, but those changes remain isolated from non-OpenAI adapters.

## Alternatives Considered

### Reuse the existing non-generic `NativeModelRequest`

Rejected because its `kwargs` bag mixes request, credential, routing, and transport concerns and cannot enforce HTTP/WebSocket request parity.

### Make only the fields of `NativeModelRequest` generic

Rejected because providers differ in complete request shape, not only in the element types of `input`, `tools`, and `kwargs`. A common field-based envelope would continue to impose LiteLLM Responses assumptions on unrelated native adapters.

### Use the OpenAI SDK `ResponseCreateParams` type directly as the internal request

Rejected because the generated mutable request type includes SDK-facing concerns and would couple the whole engine protocol directly to one SDK release. Azents owns the immutable logical request boundary while reusing official parameter types inside it.

## Migration provenance

- Historical source filename: `0151-use-generic-native-adapter-request-types.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
