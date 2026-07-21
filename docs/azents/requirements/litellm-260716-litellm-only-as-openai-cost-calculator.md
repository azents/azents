---
title: "Use LiteLLM Only as the OpenAI Cost Calculator Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: litellm-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0149-use-litellm-only-as-openai-cost-calculator.md"
---

# Use LiteLLM Only as the OpenAI Cost Calculator Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `litellm-260716`
- Source: `docs/azents/adr/litellm-260716-litellm-only-as-openai-cost-calculator.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-104) replaces LiteLLM with the official OpenAI SDK as the request and transport owner for `LLMProvider.OPENAI`. [http-260716/ADR](../adr/http-260716-openai-http-migration-by-semantic-parity.md) requires semantic parity for usage provenance and `cost_usd`, but direct OpenAI SDK responses do not contain LiteLLM's private `_hidden_params.response_cost` value used by the current adapter.

Azents does not currently own a complete pricing source for calculating OpenAI cost. Taking ownership would require maintaining model aliases, input and output token rates, cached-token rates, service tiers, built-in tool charges, and pricing updates. LiteLLM remains a dependency for non-OpenAI providers and exposes a public `completion_cost()` API that accepts Responses usage and supports `call_type="responses"`.

The clean transport migration must not retain LiteLLM request transformation, response normalization, or fallback behavior for OpenAI merely to recover cost metadata.

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
