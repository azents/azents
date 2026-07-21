---
title: "Session-Scoped Runner Operation Concurrency Historical Requirements Reconstruction"
created: 2026-07-10
implemented: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: operation-260710
historical_reconstruction: true
migration_source: "docs/azents/design/session-scoped-runner-operation-concurrency.md"
---

# Session-Scoped Runner Operation Concurrency Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `operation-260710`
- Source: `docs/azents/design/operation-260710-runner-operation-concurrency.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

One Agent Runtime Runner serves every Agent Session attached to the Agent. The current Runner run loop applies one default limit of four active operations to the entire Runtime. Operations from unrelated root and subagent Sessions therefore contend for the same slots, while the transport can continue accumulating work in an unbounded queue.

This is especially visible during Session initialization. The Skill projection hook scans Runtime filesystem roots through `file.list` and `file.read`. Concurrent new Sessions repeat that scan while model-driven process and file operations use the same Runner. Long-yield `process.start` operations can occupy all four slots and delay short filesystem operations for unrelated Sessions.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Enforce a default limit of 10 active ordinary operations per Agent Session.
- Enforce a default safety ceiling of 50 active ordinary operations per Runtime.
- Schedule Session-owned and system work fairly without cross-Session head-of-line blocking.
- Preserve FIFO order within one owner queue.
- Keep termination and mandatory cleanup available when ordinary capacity is saturated.
- Bound pending work and return explicit overload and timeout results.
- Carry operation ownership through Control, gRPC, Runner, background completion, and diagnostics.
- Make queue wait distinguishable from execution time in production telemetry.

## Non-goals

- Partitioning execution capacity by operation type.
- Deduplicating or single-flighting Skill projection scans.
- Changing Agent Runtime ownership; one Runtime remains Agent-scoped and shared by its Sessions.
- Introducing a legacy protocol fallback.
- Guaranteeing one global FIFO order across Sessions.
- Inferring Runtime lifecycle from Runner operation pressure or Runner process signals.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
