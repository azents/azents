---
title: "Use an OpenAI-Native Responses Transport Family Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: openai-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0147-openai-native-responses-transport-family.md"
---

# Use an OpenAI-Native Responses Transport Family Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `openai-260716`
- Source: `docs/azents/adr/openai-260716-openai-responses-transport-family.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently lowers its canonical event transcript through `LiteLLMResponsesLowerer` and calls the Responses API through LiteLLM. OpenAI Responses WebSocket mode is available only through the official OpenAI protocol and SDK; LiteLLM 1.91.3 exposes no public outbound-client WebSocket transport, and its private `_aresponses_websocket()` entry point is documented for proxy use only.

Using the OpenAI SDK for WebSocket while retaining LiteLLM for the OpenAI HTTP fallback would create two transformation paths for the same provider. Even if both start from the same Azents events, LiteLLM may independently transform model identifiers, optional parameters, instructions, tools, headers, input items, stream events, and response metadata. The WebSocket default and its HTTP fallback would therefore not have a stable semantic-parity boundary.

The transport migration must preserve the existing logical execution semantics:

- the canonical event transcript remains the durable source of truth;
- compaction and file materialization happen before native request-size enforcement;
- `NativeRequestSizeGuard` continues to evaluate the final logical provider request;
- ChatGPT OAuth remains a full-context LiteLLM HTTP path with `store=false`;
- OpenAI continuation remains an in-memory transport optimization and never replaces canonical transcript lowering.

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
