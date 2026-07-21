---
title: "Use LiteLLM Only as the OpenAI Cost Calculator"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, usage, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: litellm-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0149-use-litellm-only-as-openai-cost-calculator.md"
---

# litellm-260716/ADR: Use LiteLLM Only as the OpenAI Cost Calculator

## Status

Accepted. Implementation has not started.

## Context

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-104) replaces LiteLLM with the official OpenAI SDK as the request and transport owner for `LLMProvider.OPENAI`. [http-260716/ADR](./http-260716-openai-http-migration-by-semantic-parity.md) requires semantic parity for usage provenance and `cost_usd`, but direct OpenAI SDK responses do not contain LiteLLM's private `_hidden_params.response_cost` value used by the current adapter.

Azents does not currently own a complete pricing source for calculating OpenAI cost. Taking ownership would require maintaining model aliases, input and output token rates, cached-token rates, service tiers, built-in tool charges, and pricing updates. LiteLLM remains a dependency for non-OpenAI providers and exposes a public `completion_cost()` API that accepts Responses usage and supports `call_type="responses"`.

The clean transport migration must not retain LiteLLM request transformation, response normalization, or fallback behavior for OpenAI merely to recover cost metadata.

## Decision

Normalize usage from official OpenAI SDK events and completed Responses objects into the Azents canonical usage contract. Calculate `cost_usd` by invoking LiteLLM's public cost-calculation API as a pricing utility with the explicit OpenAI model, provider, Responses call type, and provider-reported usage.

LiteLLM has no OpenAI transport responsibility in this path. It does not lower the request, send HTTP or WebSocket traffic, normalize OpenAI stream events, classify transport errors, or provide runtime fallback. The OpenAI adapter must not depend on LiteLLM private response fields or private WebSocket interfaces.

The cost-calculation wrapper is an explicit Azents-owned boundary. Tests validate the exact normalized usage and calculator arguments independently of LiteLLM transport objects. The detailed design will define unsupported-model and calculator-failure behavior consistently with the optional `cost_usd` canonical field.

## Consequences

- OpenAI request and response semantics are owned by the OpenAI-native adapter while existing pricing coverage is reused.
- OpenAI cost calculation no longer depends on `_hidden_params.response_cost`.
- LiteLLM remains a runtime dependency because it still serves non-OpenAI providers, so this decision adds no new package dependency.
- LiteLLM pricing-map changes can affect calculated cost and require focused parity tests when the dependency is updated.
- Azents can later replace the pricing utility without changing the OpenAI lowerer or transport adapters.

## Alternatives Considered

### Maintain an Azents-owned OpenAI pricing table

Rejected for this migration because Azents has no current pricing authority and would need to take ownership of model aliasing, cache and service-tier rates, built-in tool pricing, and update cadence before the transport can be migrated.

### Keep the LiteLLM OpenAI HTTP path to obtain `_hidden_params.response_cost`

Rejected because it would preserve two OpenAI request and normalization paths and violate the clean OpenAI-native transport boundary.

### Omit OpenAI cost after migration

Rejected because the existing canonical usage and run provenance include `cost_usd`, and [http-260716/ADR](./http-260716-openai-http-migration-by-semantic-parity.md) requires usage and cost parity for the HTTP migration.

## Migration provenance

- Historical source filename: `0149-use-litellm-only-as-openai-cost-calculator.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
