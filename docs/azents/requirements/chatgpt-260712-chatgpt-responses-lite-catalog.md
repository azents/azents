---
title: "ChatGPT Responses Lite Catalog Integration Historical Requirements Reconstruction"
created: 2026-07-12
implemented: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: chatgpt-260712
historical_reconstruction: true
migration_source: "docs/azents/design/chatgpt-responses-lite-catalog.md"
---

# ChatGPT Responses Lite Catalog Integration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `chatgpt-260712`
- Source: `docs/azents/design/chatgpt-260712-chatgpt-responses-lite-catalog.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

ChatGPT subscription models can require either the standard Responses request contract or the Responses Lite request contract. Model names are not a stable protocol signal, and LiteLLM does not automatically discover or lower the Responses Lite contract for ChatGPT OAuth models.

Azents already stores model selections as immutable Agent snapshots and already separates system catalogs from provider-integration catalogs. ChatGPT OAuth currently uses the shared system catalog projected from LiteLLM metadata, so it cannot represent account-visible models or the backend `use_responses_lite` capability.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Discover account-visible ChatGPT models from the authenticated Codex backend model catalog.
- Select the Responses transport from backend metadata rather than model-name allowlists.
- Reuse the existing integration catalog, snapshot, sync-attempt, picker, and Agent model-selection snapshot infrastructure.
- Lower Responses Lite requests in Azents while continuing to use LiteLLM for transport and streaming response parsing.
- Preserve Azents client identity and existing transcript replay semantics.

## Non-goals

- Do not change Agent model-selection snapshot semantics.
- Do not update existing Agent snapshots after a catalog refresh.
- Do not upgrade LiteLLM as part of this feature.
- Do not switch to LiteLLM's native `chatgpt/` provider.
- Do not impersonate the Codex CLI client identity.
- Do not retry a failed Responses Lite request with the standard Responses contract.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
