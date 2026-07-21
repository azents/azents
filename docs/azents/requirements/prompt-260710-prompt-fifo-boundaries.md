---
title: "Per-Prompt Models Form FIFO Run Boundaries Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: prompt-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0103-per-prompt-model-fifo-run-boundaries.md"
---

# Per-Prompt Models Form FIFO Run Boundaries Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `prompt-260710`
- Source: `docs/azents/adr/prompt-260710-prompt-fifo-boundaries.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[label-260709/ADR](../adr/label-260709-label-targets.md) introduced Agent-owned label-based model targets partly to support future chat-time model selection. The current execution path resolves one effective main model before an `AgentRun` starts and keeps that model fixed for the full run. At the same time, the input buffer may promote multiple queued human inputs together and may inject newly queued input at later model-call boundaries within the active run.

Adding a model label only to the public message request would therefore not guarantee per-prompt behavior. Inputs that selected different models could be folded into one run whose `RunRequest` contains only one main model. Switching the model inside an active run would instead make retry, compaction, context budgeting, subagent inheritance, and run-level observability depend on turn-local model state.

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
