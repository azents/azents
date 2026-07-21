---
title: "Normalize Provider Tool Semantic Transcript Content Historical Requirements Reconstruction"
created: 2026-07-18
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: semantic-260718
historical_reconstruction: true
migration_source: "docs/azents/adr/0167-normalize-provider-tool-semantic-transcript.md"
---

# Normalize Provider Tool Semantic Transcript Content Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `semantic-260718`
- Source: `docs/azents/adr/semantic-260718-semantic-transcript.md`
- Historical source date basis: `2026-07-18`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents stores provider-hosted model output as `provider_tool_call` and `provider_tool_result` canonical events with opaque `native_artifact` payloads for strict same-native replay. Canonical fields are the durable source of truth; native artifacts are only compatible replay optimizations.

The current generic compaction renderer includes canonical provider-tool call arguments and result output. However, provider APIs do not expose hosted tools through one uniform call/result shape. For example, OpenAI Responses web search exposes query and source metadata inside a `web_search_call.action` native item, emits no separate tool-result body, and places the synthesized answer and citation annotations in the assistant message. The current canonical web-search call stores `arguments=None`, so compaction and cross-native lowering preserve only that web search occurred, while query, source, and citation metadata remain available only inside the opaque native artifact.

Adding provider-tool-specific parsing directly to compaction would violate the adapter boundary and require compaction changes whenever a new hosted tool is introduced. Depending only on `ProviderToolResultPayload.output` would also miss providers and tools whose meaningful data appears in call items, assistant annotations, generated files, or other native output structures.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Preserve provider-exposed semantic content needed for future model continuation and compaction.
- Keep provider-specific extraction inside adapter output normalizers.
- Give compaction, token estimation, continuity rendering, and cross-native lowering one provider-neutral projection.
- Avoid requiring compaction changes for each newly supported provider-hosted tool.
- Preserve strict native-artifact compatibility and replay rules.
- Bound model-visible content independently from opaque audit/native artifacts.

## Non-goals

- Reconstruct result bodies that a provider does not expose.
- Store complete fetched pages or hidden provider context.
- Make provider-tool execution owned or retryable by the Azents client-tool executor.
- Interpret opaque native artifacts outside their owning adapter.
- Guarantee that every provider exposes equivalent provenance or result detail.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

- Canonical transcript remains the durable semantic source of truth.
- `NativeArtifact.item` remains opaque outside the adapter that owns it.
- Provider-specific wire types and discriminators must not escape adapter normalizers.
- Canonical content must support deterministic token estimation and bounded compaction rendering.
- File and attachment output continues to use shared `ToolOutput` / FilePart resource policy.
- New canonical fields form a persistent event contract and require migration and compatibility planning.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
