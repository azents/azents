---
title: "Model Unread Run Results as Session-Shared State Historical Requirements Reconstruction"
created: 2026-07-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: shared-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0174-session-shared-unread-run-result-state.md"
---

# Model Unread Run Results as Session-Shared State Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `shared-260720`
- Source: `docs/azents/adr/shared-260720-shared-unread-result.md`
- Historical source date basis: `2026-07-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents needs to distinguish an AgentSession whose latest completed Run result has not yet been reviewed in the Web UI. The Agent rail should display this attention state after a Run finishes and remove it after the result is reviewed.

AgentSessions are workspace-shared conversation boundaries. Multiple workspace members may open the same Session and inspect the same durable transcript. The unread result state therefore needs an explicit ownership scope rather than being inferred from `AgentSession.run_state`, `updated_at`, or browser-local state.

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
