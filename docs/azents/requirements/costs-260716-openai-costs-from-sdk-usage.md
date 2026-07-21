---
title: "Calculate OpenAI-Compatible Costs from SDK Usage Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: costs-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0158-calculate-openai-compatible-costs-from-sdk-usage.md"
---

# Calculate OpenAI-Compatible Costs from SDK Usage Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `costs-260716`
- Source: `docs/azents/adr/costs-260716-openai-costs-from-sdk-usage.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Official OpenAI Responses objects report token usage but do not report a dollar cost. The current LiteLLM transport injects `cost_usd` through private `_hidden_params.response_cost` metadata. Removing LiteLLM from OpenAI API-key and ChatGPT OAuth request, transport, and normalization paths therefore requires an explicit replacement for cost calculation.

[litellm-260716/ADR](../adr/litellm-260716-litellm-only-as-openai-cost-calculator.md) selected LiteLLM's public pricing API for OpenAI API-key calls. [chatgpt-260716/ADR](../adr/chatgpt-260716-chatgpt-oauth-in-openai-http-migration.md) subsequently added ChatGPT OAuth to the same official-SDK HTTP migration. The cost contract must now cover both migrated providers without reintroducing LiteLLM transport ownership.

ChatGPT OAuth calls use a subscription credential rather than an OpenAI Platform API key. A public API price-map result is therefore an estimate for product continuity, not a statement of the user's actual ChatGPT subscription invoice.

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
