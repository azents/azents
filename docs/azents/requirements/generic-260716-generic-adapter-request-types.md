---
title: "Use Generic Native Adapter Request Types Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: generic-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0151-use-generic-native-adapter-request-types.md"
---

# Use Generic Native Adapter Request Types Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `generic-260716`
- Source: `docs/azents/adr/generic-260716-generic-adapter-request-types.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[execution-260527/ADR](../adr/execution-260527-execution-transcript-normalization.md) designed the model adapter boundary as generic over each adapter's native request and stream event types:

- `AdapterLowerer[TNativeRequest]`;
- `PostLowerFilter[TNativeRequest]`;
- `ModelAdapter[TNativeRequest, TNativeStreamEvent]`;
- `AdapterOutputNormalizer[TNativeStreamEvent]`.

The first implementation collapsed that design into one non-generic `NativeModelRequest` with `model`, dictionary-based `input` and `tools`, and an untyped `kwargs` bag. This reduced the initial implementation surface while LiteLLM Responses was the only transport family, but it mixed logical request parameters, provider routing data, client credentials, and transport options in one object.

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-106) introduces an OpenAI-native Responses transport family, and [http-260716/ADR](../adr/http-260716-openai-http-migration-by-semantic-parity.md) requires semantic request parity across primary sampling, compaction, and automatic Session title generation. Reusing the untyped request bag would make the OpenAI HTTP and later WebSocket transports depend on implicit dictionary conventions rather than one enforceable request contract.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
