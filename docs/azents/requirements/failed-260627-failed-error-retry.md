---
title: "Failed-run Error Retry and Finalization Historical Requirements Reconstruction"
created: 2026-06-27
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: failed-260627
historical_reconstruction: true
migration_source: "docs/azents/adr/0084-failed-run-error-retry.md"
---

# Failed-run Error Retry and Finalization Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `failed-260627`
- Source: `docs/azents/adr/failed-260627-failed-error-retry.md`
- Historical source date basis: `2026-06-27`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently treats many failed-run errors as terminal immediately. A model call failure, empty model output, engine/runtime exception, or command failure can append a durable `system_error`, mark `agent_runs.status` as `FAILED`, and emit `RunComplete` before any retry policy can decide whether the failure was transient.

This causes three product problems:

- Goal continuation can repeatedly resume after unrecoverable failed-run errors and pollute context with repeated continuation/error events.
- Transient failed-run errors are exposed as final user-visible errors without a bounded automatic retry window.
- The UI mostly shows a red error text instead of live retry state, recovery affordances, or next action guidance.

The current failed-run finalization logic is also split across multiple boundaries, including `AgentRunExecution`, `AgentEngineAdapter`, `RunExecutor`, `CommandExecutor`, and `SessionRunnerErrorReporter`. Retry requires first separating attempt failure from terminal failed-run finalization.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Goal continuation is allowed only after a terminal run whose durable status is `COMPLETED`.

Goal continuation must not be triggered merely because the stream emitted `RunComplete`. Failed-run errors also end with `RunComplete` after finalization, so the idle continuation decision must read the durable run terminal status, not only the stream boundary event.

Goal continuation is blocked when the latest relevant run status is any non-success terminal state, including:

- `FAILED`;
- `STOPPED`;
- `CANCELLED`;
- `INTERRUPTED`.

Goal continuation is also blocked while retry is in progress because the run remains `RUNNING` and the session must not transition through the normal idle continuation path.

This makes retry responsible for recovering failed attempts, while Goal continuation is responsible only for pursuing active goals after successful progress. Retry exhaustion or stop-during-retry therefore does not enqueue a new `goal_continuation` input and does not pollute context with repeated continuation/error cycles.

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
