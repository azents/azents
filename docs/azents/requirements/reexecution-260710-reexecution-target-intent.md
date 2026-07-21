---
title: "Re-Execution Preserves Model Target Intent Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: reexecution-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0107-reexecution-model-target-intent.md"
---

# Re-Execution Preserves Model Target Intent Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `reexecution-260710`
- Source: `docs/azents/adr/reexecution-260710-reexecution-target-intent.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Message editing and failed-run recovery create new execution boundaries after an earlier prompt already carried a requested model target and reasoning effort. The new run could inherit the session's latest profile, reuse the earlier run's resolved model snapshot, or preserve the original requested target intent and resolve it again.

Reusing the session profile can silently change the edited or retried prompt's model. Reusing a resolved snapshot preserves the prior physical model but bypasses the current target policy and the dynamic-routing boundary established by [time-260710/ADR](../adr/time-260710-time-target-resolution.md).

Automatic provider/run retry is different: it occurs inside the same `AgentRun`, where model and effort are already fixed.

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
