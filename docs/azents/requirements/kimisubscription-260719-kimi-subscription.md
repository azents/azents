---
title: "Kimi Subscription Provider Historical Requirements Reconstruction"
created: 2026-07-19
implemented: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: kimisubscription-260719
historical_reconstruction: true
migration_source: "docs/azents/design/kimi-subscription-provider.md"
---

# Kimi Subscription Provider Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `kimisubscription-260719`
- Source: `docs/azents/design/kimisubscription-260719-kimi-subscription.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents cannot currently use a Kimi Code subscription. Users can access Kimi only through unrelated providers such as OpenRouter, while the official Kimi CLI supports user-authorized subscription credentials, account-visible models, token refresh, and quota inspection.

The feature must connect a workspace to a Kimi subscription without exposing tokens, preserve the existing provider/catalog/runtime boundaries, and fail safely if Kimi changes or rejects the public CLI contract.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Connect a workspace-scoped Kimi subscription through device authorization.
- Store access token, refresh token, and stable device identity only in encrypted storage.
- Refresh tokens before model listing, inference, compaction, title generation, and usage reads.
- Populate an integration-scoped catalog from the authenticated Kimi `/models` endpoint.
- Run selectable Kimi models through the existing LiteLLM execution path.
- Show normalized Kimi subscription usage in existing usage surfaces.
- Provide deterministic unit, API, generated-client, and frontend coverage in CI.

## Non-goals

- Add a Moonshot developer API-key provider.
- Add Kimi browser callback authorization.
- Add Kimi Search or Fetch tools.
- Add a Kimi-native Azents transport.
- Persist subscription-usage history or financial accounting.
- Guarantee live-provider availability in normal CI.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

- Kimi continues accepting its public CLI client identity from third-party user agents.
- Fixed product-neutral device labels satisfy provider validation.
- LiteLLM's Moonshot provider continues to support Kimi Code's chat-completion dialect for arbitrary account-visible model aliases.
- Kimi `/models` and `/usages` remain compatible with the official CLI shapes.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
