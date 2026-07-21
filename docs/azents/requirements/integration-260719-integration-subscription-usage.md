---
title: "Read Subscription Usage Through Provider Integrations Historical Requirements Reconstruction"
created: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: integration-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0169-integration-scoped-subscription-usage.md"
---

# Read Subscription Usage Through Provider Integrations Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `integration-260719`
- Source: `docs/azents/adr/integration-260719-integration-subscription-usage.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents supports workspace-scoped ChatGPT OAuth and xAI OAuth integrations that use a user's subscription credential for model execution. The LLM Settings surface shows connection and enabled state, but it does not show the provider-side subscription limits that determine whether the integration can continue serving runs.

This information is different from AgentRun token usage and context-window pressure. Run usage describes one resolved model execution. Subscription usage describes an external account quota shared by every Azents execution and other clients using the same provider account.

Current upstream clients expose authenticated usage data, but the contracts are provider-specific and not documented as stable public APIs:

- OpenAI Codex reads ChatGPT rate-limit windows, credits, spend control, and plan metadata from the ChatGPT backend.
- Grok Build reads xAI credit usage and billing details through the CLI proxy, and can replace inline usage with a provider-managed external usage URL through remote settings.

Azents must expose useful operational quota state without leaking OAuth credentials, raw billing payloads, sensitive financial details, or provider-specific wire contracts into the public API and frontend.

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
