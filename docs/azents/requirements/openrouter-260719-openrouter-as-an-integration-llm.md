---
title: "Add OpenRouter as an Integration-Scoped LLM Provider Historical Requirements Reconstruction"
created: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: openrouter-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0169-add-openrouter-as-an-integration-scoped-llm-provider.md"
---

# Add OpenRouter as an Integration-Scoped LLM Provider Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `openrouter-260719`
- Source: `docs/azents/adr/openrouter-260719-openrouter-as-an-integration-llm.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

OpenRouter provides one account-scoped API surface for models from many publishers. Its primary product value is that users can try newly available models without waiting for Azents to add each model individually.

Azents already distinguishes system catalogs from integration-scoped catalogs and projects provider model metadata into a canonical capability contract. OpenRouter model availability depends on the API key and the account's provider preferences, while its catalog changes more quickly than an Azents release cycle or a bundled LiteLLM metadata snapshot.

A curated Azents allowlist would make OpenRouter behave like a small set of separately integrated providers and would remove the main reason to support it. At the same time, catalog visibility must remain separate from capability claims: exposing a model does not mean Azents can safely advertise every modality, parameter, hosted tool, or provider-specific optimization reported for that model.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Preserve OpenRouter's ability to expose arbitrary account-available models without Azents releases.
- Keep model availability scoped to the configured OpenRouter integration.
- Separate model visibility from conservative Azents capability projection.
- Reuse Azents canonical model selection and LiteLLM Responses runtime boundaries.
- Define explicit ownership for OpenRouter routing and data-policy controls.

## Non-goals

- Maintain an Azents-curated OpenRouter model allowlist.
- Guarantee identical capability behavior across every upstream model and provider route.
- Add a user-configurable OpenRouter-compatible base URL.
- Treat OpenRouter publishers as separate Azents credential providers.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

- Agent model selection keeps existing snapshot semantics.
- Catalog reads use stored projections rather than calling OpenRouter on the normal read path.
- OpenRouter credentials remain backend-only and use the existing API-key secret contract.
- Unknown model publishers must not inherit another publisher's provider-specific lowering behavior.
- Unsupported or unverified capabilities must be hidden without hiding an otherwise usable text-output model.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
