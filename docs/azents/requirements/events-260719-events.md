---
title: "Use Single Durable Events for Provider Tool Items Historical Requirements Reconstruction"
created: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: events-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0168-use-single-provider-tool-events.md"
---

# Use Single Durable Events for Provider Tool Items Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `events-260719`
- Source: `docs/azents/adr/events-260719-events.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[semantic-260718/ADR](../adr/semantic-260718-semantic-transcript.md) introduced a shared provider-neutral `ProviderToolSemanticContent` contract for provider-hosted tools while retaining both `provider_tool_call` and `provider_tool_result` event kinds. That contract correctly allows a single native hosted-tool item to carry both semantic input and output, but the initial implementation still classifies OpenAI Responses `image_generation_call` as `provider_tool_result`.

This leaves one native provider item represented through a special result event even though other hosted-tool output items, including Web search, file search, code interpreter, and MCP calls, are represented as `provider_tool_call`. It also keeps provider result handling, frontend call/result merging, and separate tool-level `attachments` fields solely for generated-image delivery.

The distinction does not reflect provider execution ownership. Provider-hosted tools execute entirely inside the provider response. Unlike Azents client tools, they do not require a durable request event followed by a separately executed result event. A native item such as `image_generation_call` already contains its lifecycle state and provider result.

[generated-260717/ADR](../adr/generated-260717-generated-images-as-file-resources.md) remains correct that a successful generated image requires two independently stored resources:

- a ModelFile-backed `FileOutputPart` for later model input; and
- an Exchange-backed attachment for user delivery.

The question is how those references are represented in the durable event transcript, not whether both resources exist.

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
