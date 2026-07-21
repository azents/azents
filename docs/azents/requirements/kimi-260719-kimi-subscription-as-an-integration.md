---
title: "Add Kimi Subscription as an Integration-Scoped Provider Historical Requirements Reconstruction"
created: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: kimi-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0171-add-kimi-subscription-as-an-integration-scoped-provider.md"
---

# Add Kimi Subscription as an Integration-Scoped Provider Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `kimi-260719`
- Source: `docs/azents/adr/kimi-260719-kimi-subscription-as-an-integration.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Kimi Code subscriptions can authorize the official Kimi CLI through an RFC 8628 device flow and use the resulting access token against the Kimi Code inference, model-listing, and usage endpoints. This credential is operationally different from a Moonshot developer API key: billing and quota belong to a user subscription, tokens rotate, the authorization service requires a stable device identity, and account-visible models come from the authenticated Kimi Code catalog.

Azents already separates ChatGPT and xAI subscription credentials from their developer API-key providers. It also has integration-scoped model catalogs, encrypted provider credentials, runtime token refresh, and normalized subscription-usage presentation. Kimi should join those boundaries rather than introduce an independent runtime or credential store.

The implemented Kimi CLI contract inspected for this decision is MoonshotAI/kimi-cli commit `4a550effdfcb29a25a5d325bf935296cc50cd417` (Kimi CLI 1.49.0, 2026-07-16).

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
