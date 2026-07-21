---
title: "Session-Owned Project Registry Historical Requirements Reconstruction"
created: 2026-06-25
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: registry-260625
historical_reconstruction: true
migration_source: "docs/azents/adr/0076-session-owned-project-registry.md"
---

# Session-Owned Project Registry Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `registry-260625`
- Source: `docs/azents/adr/registry-260625-registry.md`
- Historical source date basis: `2026-06-25`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[primary-260625/ADR](../adr/primary-260625-primary-sessions.md) defines project registrations as `AgentSession` working context, while
`AgentRuntime` owns only the physical workspace and runtime lifecycle. Phase 4-A removed
`AgentSession` runtime ownership, but the existing `session_workspace_projects` and project
registration request tables still use `agent_runtime_id` as their durable ownership key.

Keeping project rows runtime-owned would recreate hidden runtime-global context. It would also make
future URL-selected sessions and multiple team sessions ambiguous because different sessions under the
same agent would see the same project catalog by default.

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
