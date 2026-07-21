---
title: "Sandbox Runtime / Workspace State Boundary Historical Requirements Reconstruction"
created: 2026-05-24
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: boundary-260524
historical_reconstruction: true
migration_source: "docs/azents/design/sandbox-runtime-workspace-state-boundary.md"
---

# Sandbox Runtime / Workspace State Boundary Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `boundary-260524`
- Source: `docs/azents/design/boundary-260524-sandbox-boundary.md`
- Historical source date basis: `2026-05-24`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Recent production incidents exposed that the Workspace panel API and UI collapse two different control planes into one state:

- **Provider control** owns whether an Agent sandbox runtime exists, is starting, running, hibernated, deleting, lost, or failed to restore.
- **Sandbox control** owns operations inside a runtime that provider control has already considered present: workspace file list/read/write, shell command dispatch, checkpoint create/restore hooks, and command-stream readiness.

The current Workspace API returns a single Agent Workspace state union such as `READY`, `RESTORING`, `RESTORE_FAILED`, or `SANDBOX_INACTIVE`. That shape made `READY` imply both "runtime exists" and "workspace file API is usable". In production this broke down: provider control showed the Agent sandbox Pod was running, but sandbox-control worker requests returned `Sandbox control connection is unavailable`. The UI then rendered a red error with no stop/reset action, leaving the user stuck even though the system had already judged the runtime to exist.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

1. Make provider runtime state explicit in every workspace panel response.
2. Make sandbox-control workspace access state explicit and nested under runtime state, not vice versa.
3. Preserve runtime lifecycle actions whenever provider control judges a runtime to exist, even if sandbox-control is unavailable.
4. Keep state transitions idempotent:
   - Start means desired provider runtime state is running.
   - Stop means desired provider runtime state is stopped/hibernated.
   - Reset means explicitly discard durable runtime/workspace state and start fresh.
5. Remove implicit reset or fallback paths. Users must explicitly choose retry or reset when data may be discarded.
6. Treat "runtime running but workspace unavailable" as a first-class recoverable state with user actions.

## Non-goals

- This design does not change provider controller internals or introduce a new persistence backend for Kubernetes.
- This design does not require backward-compatible response fields. The API and generated client can change together.
- This design does not make sandbox-control fully stateless by itself. It assumes the existing Redis registry/command bus remains the cross-replica routing layer.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
