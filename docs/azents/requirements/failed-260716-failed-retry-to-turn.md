---
title: "Scope Failed-run Retry to One Model Turn Historical Requirements Reconstruction"
created: 2026-07-16
implemented: 2026-03-26
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: failed-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0145-scope-failed-run-retry-to-model-turn.md"
---

# Scope Failed-run Retry to One Model Turn Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `failed-260716`
- Source: `docs/azents/adr/failed-260716-failed-retry-to-turn.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[failed-260627/ADR](../adr/failed-260627-failed-error-retry.md) established durable failed-run retry state on `agent_runs` and required worker handover to preserve retry count and backoff. Its recovery language treated a running `AgentRun` as the effective retry scope.

One `AgentRun` can contain multiple model turns. The implementation consequently retained failed-attempt count, history, and backoff after a model turn recovered. A failure in a later turn continued the older turn's budget. Durable retry state also survived successful output, so REST live-state resync could restore an obsolete error card under a later inference profile.

The intended product policy is that automatic retry protects one model turn. A later model turn receives a fresh budget, while worker handover during the current turn must still preserve retry progress.

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
