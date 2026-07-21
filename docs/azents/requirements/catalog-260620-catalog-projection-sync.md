---
title: "Model Catalog Projection and Sync Historical Requirements Reconstruction"
created: 2026-06-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: catalog-260620
historical_reconstruction: true
migration_source: "docs/azents/adr/0067-model-catalog-projection-sync.md"
---

# Model Catalog Projection and Sync Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `catalog-260620`
- Source: `docs/azents/adr/catalog-260620-catalog-projection-sync.md`
- Historical source date basis: `2026-06-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Agent model selection currently lists provider models at request time. For AWS Bedrock, the API path calls `ListFoundationModels` with the user-provided integration credential. When that credential lacks `bedrock:ListFoundationModels`, the provider returns `AccessDeniedException`, which is currently wrapped as an unhandled `ListingProviderError` and surfaces as a server error.

This exposed several modeling issues:

- Model listing has different ownership depending on source. Some catalogs are managed by Azents independent of a customer credential, while others depend on a customer's provider integration.
- User-provided credential failures must not be treated as Azents server failures.
- External catalog sources such as models.dev can be slow or unstable, so request-time dependence is fragile. The design removes models.dev from model catalog source path instead of adding another sync dependency around it.
- Provider APIs and metadata catalogs have different roles: provider APIs can tell whether a model is visible for a customer integration, while metadata catalogs describe capabilities, context windows, modalities, and runtime compatibility.
- Current UI uses searchable select, which is not enough to expose sync state, sync failure, stale snapshot, infinite scroll, and capability details.
- LiteLLM currently fetches a remote model cost map at import/startup, but LiteLLM is only the current lowerer target. The runtime abstraction must remain open to any-llm or native SDK targets later.

Therefore model catalog needs an explicit sync/projection layer rather than request-time provider calls.

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
