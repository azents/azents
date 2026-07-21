---
title: "Project Subscription Usage from the Selected Composer Model Historical Requirements Reconstruction"
created: 2026-07-19
implemented: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: subscription-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0170-project-subscription-usage-from-selected-model.md"
---

# Project Subscription Usage from the Selected Composer Model Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `subscription-260719`
- Source: `docs/azents/adr/subscription-260719-subscription-usage-from.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-139) established integration-scoped live subscription usage and made each Workspace LLM Settings integration card the canonical management surface. That placement keeps credentials, enabled state, aliases, financial details, and provider usage together, but it requires users to leave an active Agent session to inspect the quota that can affect their next request.

A session can expose several selectable model targets backed by different provider integrations. The composer already identifies the model target for the next input and each selectable option carries its `llm_provider_integration_id` and provider snapshot. The session header separately displays run-scoped token and context-window usage for the active or latest run.

Subscription usage and run context usage must remain distinct:

- context usage belongs to one applied run profile and explains local compaction pressure;
- subscription usage belongs to the provider integration selected for the next composer input and can be shared across sessions and external clients.

The session needs a discoverable, low-noise usage affordance without introducing a second source of financial management or implying that provider quota is session-owned.

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
