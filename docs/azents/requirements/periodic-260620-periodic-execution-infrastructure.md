---
title: "Periodic Execution Infrastructure Historical Requirements Reconstruction"
created: 2026-06-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: periodic-260620
historical_reconstruction: true
migration_source: "docs/azents/adr/0068-periodic-execution-infrastructure.md"
---

# Periodic Execution Infrastructure Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `periodic-260620`
- Source: `docs/azents/adr/periodic-260620-periodic-execution-infrastructure.md`
- Historical source date basis: `2026-06-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents needs system-owned periodic execution for work such as model catalog source sync, projection refresh, cleanup, reconciliation, and future maintenance tasks. The immediate model catalog design assumes a periodic execution infrastructure, but that infrastructure is separate from model catalog semantics.

Earlier discussions considered Temporal. Temporal is a strong fit for durable background execution, but it is not adopted as the first implementation for these reasons:

- Temporal background task execution is clean, but Temporal scheduling is not the most intuitive fit for the current system jobs.
- Azents devserver is a standalone all-in-one local server and should not require Temporal.
- If Temporal becomes optional in distributed mode, Azents still needs an abstraction that hides Temporal from product/domain code so devserver can keep the same task contract.
- Current planned jobs are lightweight enough that Temporal would be too heavy as the first dependency.
- The design should still leave a path for heavier durable work later.

Distributed mode is already live. Production roles are separated into API, admin, runtime-control, worker, and supporting components. The existing `AgentWorker` owns agent session execution and has worker-internal recovery loops such as stuck session recovery. General system periodic jobs must not be added to `AgentWorker`.

This ADR defines a lightweight system periodic execution infrastructure. It is not the user/agent-facing scheduled task product described by [scheduled-260331/ADR](../adr/scheduled-260331-scheduled-tasks.md). User-defined schedules, cron/timezone UX, notification delivery, and agent-created scheduled work remain separate product scope.

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
