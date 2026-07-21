---
title: "Include ChatGPT OAuth in the OpenAI-Native HTTP Migration Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: chatgpt-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0152-include-chatgpt-oauth-in-openai-native-http-migration.md"
---

# Include ChatGPT OAuth in the OpenAI-Native HTTP Migration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `chatgpt-260716`
- Source: `docs/azents/adr/chatgpt-260716-chatgpt-oauth-in-openai-http-migration.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-107) and [http-260716/ADR](../adr/http-260716-openai-http-migration-by-semantic-parity.md) scoped the first OpenAI-native HTTP migration to `LLMProvider.OPENAI` and retained `LLMProvider.CHATGPT_OAUTH` on LiteLLM HTTP. That scope does not match the intended migration boundary.

Both integrations use a Responses-compatible HTTP protocol and must move through the generic native adapter pipeline established by [generic-260716/ADR](../adr/generic-260716-generic-adapter-request-types.md). ChatGPT OAuth has a distinct Responses Lite request dialect and storage requirement, but those differences do not justify retaining a second LiteLLM-owned request and transport path inside the OpenAI-compatible provider family.

The current provider contracts differ in one important respect:

- OpenAI API-key requests do not need an explicit `store` value and may use stored-response continuation when otherwise eligible;
- ChatGPT OAuth requires `store=false`, provider-specific Responses Lite headers and input items, encrypted reasoning continuation data, and complete logical input on every request.

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
