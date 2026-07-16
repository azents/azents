---
title: "ADR-0158: Calculate OpenAI-Compatible Costs from SDK Usage"
created: 2026-07-16
tags: [architecture, backend, engine, llm, openai, oauth, usage, cost]
---

# ADR-0158: Calculate OpenAI-Compatible Costs from SDK Usage

## Status

Accepted. Implementation has not started.

## Context

Official OpenAI Responses objects report token usage but do not report a dollar cost. The current LiteLLM transport injects `cost_usd` through private `_hidden_params.response_cost` metadata. Removing LiteLLM from OpenAI API-key and ChatGPT OAuth request, transport, and normalization paths therefore requires an explicit replacement for cost calculation.

ADR-0149 selected LiteLLM's public pricing API for OpenAI API-key calls. ADR-0152 subsequently added ChatGPT OAuth to the same official-SDK HTTP migration. The cost contract must now cover both migrated providers without reintroducing LiteLLM transport ownership.

ChatGPT OAuth calls use a subscription credential rather than an OpenAI Platform API key. A public API price-map result is therefore an estimate for product continuity, not a statement of the user's actual ChatGPT subscription invoice.

## Decision

Usage is normalized directly from the official SDK's completed `ResponseUsage` object for both OpenAI API-key and ChatGPT OAuth:

- `input_tokens` becomes canonical `prompt_tokens`;
- `output_tokens` becomes canonical `completion_tokens`;
- `total_tokens` remains canonical `total_tokens`;
- `input_tokens_details.cached_tokens` becomes `cached_tokens`;
- `input_tokens_details.cache_write_tokens` becomes `cache_creation_tokens`;
- `output_tokens_details.reasoning_tokens` becomes `reasoning_tokens`.

The canonical raw usage payload is the SDK usage model serialized with unset fields excluded while preserving explicit nulls and provider extras. New OpenAI-native usage does not synthesize LiteLLM `_hidden_params`.

Azents calculates `cost_usd` for both migrated providers through LiteLLM's public `completion_cost()` pricing API with an explicit model, OpenAI provider identity, and Responses call type. LiteLLM remains a synchronous in-process pricing utility only. It does not receive transport ownership, credentials, request input, response text, reasoning content, tool arguments, raw frames, or SDK client objects.

The cost wrapper supplies a minimal cost-calculation view containing only the provider-reported usage, model and applicable service tier, plus the minimum output-type and built-in-tool metadata required to account for supported provider tool charges. It does not pass model content merely to satisfy a LiteLLM response type.

For ChatGPT OAuth, `cost_usd` retains the same price-map estimate semantics as the current path. It is not actual subscription billing data.

An unsupported model, unavailable price, malformed calculator result, or calculator exception does not turn a successful model response into a failed Run. Azents preserves token usage, stores `cost_usd=None`, and emits only privacy-safe operational diagnostics. A finite non-negative calculator result is required before setting `cost_usd`.

This decision extends ADR-0149's pricing-utility boundary to ChatGPT OAuth and makes the usage source and failure behavior explicit.

## Consequences

- OpenAI-native token usage no longer depends on LiteLLM response wrappers or private hidden fields.
- Existing `cost_usd` behavior remains available for OpenAI API-key and ChatGPT OAuth turns.
- ChatGPT OAuth cost is explicitly an API price-map estimate rather than subscription invoice data.
- Pricing failure cannot discard an otherwise successful model response or its usage.
- LiteLLM pricing-map updates can change estimates independently of OpenAI SDK transport behavior.
- Cost fixtures must cover normal, cached, cache-write, reasoning, service-tier, built-in-tool, unsupported-model, invalid-result, and calculator-failure cases for both providers.
- Failed or abandoned physical SDK retries without a successful provider usage object cannot be included in canonical usage or cost.

## Alternatives Considered

### Calculate cost only for OpenAI API-key calls

Rejected because the HTTP migration should preserve the existing ChatGPT OAuth usage and cost projection instead of changing it as an incidental consequence of transport replacement.

### Remove cost calculation for both providers

Rejected because `cost_usd` is part of the existing canonical usage and migration parity contract.

### Maintain an Azents-owned OpenAI price table

Rejected for this migration because Azents has not accepted ownership of model aliases, cached-token rates, service tiers, built-in tool charges, and pricing update cadence.
