---
title: "Use Official OpenAI SDK Native Stream Events Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: official-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0153-use-official-openai-sdk-native-stream-events.md"
---

# Use Official OpenAI SDK Native Stream Events Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `official-260716`
- Source: `docs/azents/adr/official-260716-official-openai-sdk-stream-events.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[generic-260716/ADR](../adr/generic-260716-generic-adapter-request-types.md) restores the generic native adapter pipeline. The official OpenAI SDK already parses Responses HTTP streams into the typed `ResponseStreamEvent` union, including typed response, output item, usage, error, and delta fields.

Introducing an Azents-owned dictionary event wrapper between the SDK adapter and the output normalizer would discard useful type information and duplicate part of the SDK contract. The required compatibility property is semantic native-event round-trip: completed native output items and provider extension fields must survive serialization into sanitized durable native artifacts and replay through the matching lowerer. Byte-for-byte HTTP or SSE frame preservation is not required by [http-260716/ADR](../adr/http-260716-openai-http-migration-by-semantic-parity.md).

The SDK may loosely construct a known event class for a wire discriminator unknown to the installed SDK version. This is an intentional forward-compatible fallback: the original `type` value and extra fields remain available on the model. Azents does not need to replace the typed event model to accommodate that fallback.

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
