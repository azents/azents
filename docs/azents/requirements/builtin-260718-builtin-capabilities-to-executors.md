---
title: "Resolve built-in capabilities to model-specific executors Historical Requirements Reconstruction"
created: 2026-07-18
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: builtin-260718
historical_reconstruction: true
migration_source: "docs/azents/adr/0166-resolve-builtin-capabilities-to-model-specific-executors.md"
---

# Resolve built-in capabilities to model-specific executors Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `builtin-260718`
- Source: `docs/azents/adr/builtin-260718-builtin-capabilities-to-executors.md`
- Historical source date basis: `2026-07-18`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents exposes model-scoped built-in capabilities such as `web_search` and
`image_generation`. The existing runtime contract treats every selected built-in as a
provider-hosted tool and passes it directly to the provider request lowerer.

That assumption does not hold for every provider. OpenAI and ChatGPT models can execute
`image_generation` as a provider-hosted Responses tool. Grok language models support
function calling, while image creation is provided through the separate xAI Imagine API.
Azents can therefore provide the same user-visible capability to Grok by exposing a
client-executed function tool that calls Imagine with the selected xAI integration.

The xAI language-model catalog and the LiteLLM model metadata used by Azents do not
publish a language-model-to-Imagine capability relation. They do publish whether a
language model supports function calling. Maintaining a Grok model identifier allowlist
would require an Azents release for each new model and alias.

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
