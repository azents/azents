---
title: "Provider-hosted web search runs through normalized capability and Agent opt-in Historical Requirements Reconstruction"
created: 2026-06-17
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: hosted-260617
historical_reconstruction: true
migration_source: "docs/azents/adr/0064-provider-hosted-web-search.md"
---

# Provider-hosted web search runs through normalized capability and Agent opt-in Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `hosted-260617`
- Source: `docs/azents/adr/hosted-260617-hosted-web-search.md`
- Historical source date basis: `2026-06-17`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents aligns Agent form and runtime decisions through `normalized_capabilities` in model catalog snapshot. `web_search` is a hosted tool executed server-side by provider, and each provider/model can enable the same semantic capability in different ways.

- OpenAI / ChatGPT OAuth family receives web search as Responses tool definition.
- Gemini family receives Google Search grounding tool definition.
- Anthropic family receives versioned server tool definition.
- Some LiteLLM-compatible providers may require separate request parameter.

Existing code already has `BuiltinToolSpec`, Agent `model_parameters.builtin_tools`, catalog `built_in_tools.supported`, and canonical `provider_tool_call` / `provider_tool_result` events. However, current event runtime does not lower Agent-enabled hosted tool to native LiteLLM Responses request.

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
