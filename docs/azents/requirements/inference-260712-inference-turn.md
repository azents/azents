---
title: "Use Session Current Inference State Per Turn Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: inference-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0140-use-session-current-inference-state-per-turn.md"
---

# Use Session Current Inference State Per Turn Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `inference-260712`
- Source: `docs/azents/adr/inference-260712-inference-turn.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Earlier inference-profile ADRs bind one requested and resolved model profile to an entire AgentRun. That boundary requires pending inputs with another model to end the current run or wait for a later run. The sequential preparation design instead resolves each model-bearing input before the next turn and stores the final applied configuration on the session.

An AgentRun may contain multiple turns. There is no product requirement that every turn in one AgentRun use the same model, and actual provider/model provenance is internal execution data rather than a chat UI contract.

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
