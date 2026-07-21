---
title: "xAI API Key Provider Historical Requirements Reconstruction"
created: 2026-07-10
implemented: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: xai-260710
historical_reconstruction: true
migration_source: "docs/azents/design/xai-api-key-provider.md"
---

# xAI API Key Provider Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `xai-260710`
- Source: `docs/azents/design/xai-260710-xai-api-key.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents supports xAI through an experimental user-authorized OAuth integration, but it does not expose the standard xAI developer API-key integration. Users with an xAI API key cannot create a stable, developer-billed provider integration even though the existing LiteLLM Responses path can invoke current Grok models successfully.

The API-key and OAuth products must remain separate. They use the same xAI inference protocol and model family, but differ in credentials, billing, entitlement, refresh lifecycle, and setup UX.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Add a stable workspace-scoped xAI API-key provider.
- Store the API key only in encrypted `LLMProviderIntegration` secrets.
- Reuse the validated xAI Responses API, system-instruction, tool, and model-catalog paths.
- Allow xAI API-key and xAI OAuth integrations to coexist in one workspace.
- Present a clear UI distinction between developer API billing and experimental account OAuth.
- Keep provider behavior capability-oriented so future providers can reuse the same transport policies.

## Non-goals

- Replace, merge, or stabilize the xAI OAuth provider.
- Validate API keys or fetch models from xAI during integration CRUD.
- Add xAI image, video, audio, X search, or code execution tools.
- Add provider-specific retry behavior in this feature.
- Correct historical LiteLLM reasoning-effort metadata for every legacy Grok model.
- Introduce a generic provider plugin framework.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
