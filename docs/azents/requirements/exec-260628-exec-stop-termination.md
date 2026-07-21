---
title: "User Stop Terminates Session-Owned Runtime Exec Processes Historical Requirements Reconstruction"
created: 2026-06-28
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: exec-260628
historical_reconstruction: true
migration_source: "docs/azents/adr/0083-runtime-exec-user-stop-termination.md"
---

# User Stop Terminates Session-Owned Runtime Exec Processes Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `exec-260628`
- Source: `docs/azents/adr/exec-260628-exec-stop-termination.md`
- Historical source date basis: `2026-06-28`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[exec-260627/ADR](../adr/exec-260627-exec-process.md) introduced runner-owned runtime exec processes exposed through `exec_command` and `write_stdin`. Those processes are owned by an `AgentSession` and live in Runtime Runner memory. [preemptive-260607/ADR](../adr/preemptive-260607-preemptive-stop.md) defines user stop as a preemptive interrupt: the run must close promptly as interrupted and must not wait for foreground tools to finish.

Without an explicit exec-process stop policy, user stop can interrupt the worker-side tool wait while leaving the already-started runner process alive. That is undesirable for user intent: when a user presses stop during a running shell command, they expect work started by that session to stop too. At the same time, worker graceful shutdown or handover is not user intent. It is an execution-owner transition and should not kill useful runner-owned processes merely because one worker is exiting.

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
