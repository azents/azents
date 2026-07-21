---
title: "Define the OpenAI Responses WebSocket Lifecycle Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: responses-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0150-openai-responses-websocket-lifecycle.md"
---

# Define the OpenAI Responses WebSocket Lifecycle Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `responses-260716`
- Source: `docs/azents/adr/responses-260716-openai-responses-websocket-lifecycle.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-105) established an OpenAI-native Responses transport family in which HTTP and WebSocket consume the same complete logical request and SDK HTTP is the physical fallback. The HTTP phase is now implemented for OpenAI API-key and ChatGPT OAuth sampling, compaction, and automatic Session title generation. [standard-260716/ADR](../adr/standard-260716-standard-responses-for-chatgpt-oauth.md) also removed the Responses Lite dialect and standardized ChatGPT OAuth on the normal Responses request contract.

The WebSocket work is therefore a physical transport addition to the existing `OpenAIResponsesRequest`, adapter, normalizer, watchdog, and failed-Run boundaries. It does not introduce another lowerer, provider dialect, canonical event format, or tool executor.

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

These constraints do not require further product-level discussion:

- WebSocket and HTTP consume the same complete `OpenAIResponsesRequest` after all lowerers, filters, compaction, file materialization, and size guards.
- LiteLLM does not send fallback requests for OpenAI-compatible providers.
- One socket processes one logical response at a time.
- Successful sequential responses may reuse a healthy socket within its chosen owner scope.
- User Stop, timeout, cancellation, premature close, framing failure, or decode failure before terminal completion closes and invalidates the socket.
- SDK automatic reconnect stays disabled.
- A new socket generation starts without a WebSocket continuation boundary.
- ChatGPT OAuth uses full logical input, `store=false`, encrypted reasoning inclusion, and no `previous_response_id`.
- Unknown transport metadata does not create live or durable model output.
- Requests containing an explicit `stop` option use HTTP.
- Custom OpenAI-compatible base URLs are not assumed to support WebSocket.
- Compaction and automatic Session title generation remain HTTP-only in the initial phase.
- No credentials, authorization codes, account headers, request or response bodies, response IDs, response text, or raw frames are logged or retained as evidence.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
