---
title: "Resolve Prompt Model Targets at Run Time Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: time-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0105-run-time-model-target-resolution.md"
---

# Resolve Prompt Model Targets at Run Time Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `time-260710`
- Source: `docs/azents/adr/time-260710-time-target-resolution.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[label-260709/ADR](../adr/label-260709-label-targets.md) introduced Agent-owned label-based model targets, and [prompt-260710/ADR](../adr/prompt-260710-prompt-fifo-boundaries.md) made a prompt's requested target a FIFO run boundary. A target can either be resolved to a model snapshot when the server accepts the prompt or remain a durable routing intent until its `AgentRun` starts.

Freezing the current option snapshot at input acceptance makes queued execution deterministic, but it turns the label into an alias that is dereferenced only once. That limits the target abstraction to static model selection and makes it harder to evolve the same contract into dynamic model routing based on current policy, availability, capability, or cost.

Resolving later means Agent target configuration may change while an input is queued. Silent fallback would hide that change and could execute a different model than the requested target contract permits.

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
