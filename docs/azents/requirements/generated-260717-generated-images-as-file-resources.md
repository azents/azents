---
title: "Materialize Provider-Generated Images as File Resources Historical Requirements Reconstruction"
created: 2026-07-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: generated-260717
historical_reconstruction: true
migration_source: "docs/azents/adr/0164-materialize-provider-generated-images-as-file-resources.md"
---

# Materialize Provider-Generated Images as File Resources Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `generated-260717`
- Source: `docs/azents/adr/generated-260717-generated-images-as-file-resources.md`
- Historical source date basis: `2026-07-17`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The provider-hosted `image_generation` tool returns image bytes inside a provider-native response item, commonly as Base64. Azents already normalizes the provider call lifecycle, but its current image result projection creates an unavailable placeholder attachment and removes the native `result` before durable storage. The image is therefore neither downloadable by the user nor available as rich input to a later model call.

Raw image payloads cannot become canonical event data. Durable events, database rows, REST/WebSocket projections, frontend state, logs, and native artifacts must remain free of raw bytes, inline Base64, and data URLs. At the same time, a successful image-generation result has two independent consumers:

- the model needs a `FilePart` backed by a normalized ModelFile;
- the user needs an Attachment backed by an Exchange file.

The semantic behavior must be consistent across the OpenAI SDK, ChatGPT OAuth, and LiteLLM lowerers. Provider-specific response parsing and request dialect translation remain adapter-local.

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
