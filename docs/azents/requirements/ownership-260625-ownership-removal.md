---
title: "Remove AgentSession Runtime Ownership Historical Requirements Reconstruction"
created: 2026-06-25
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: ownership-260625
historical_reconstruction: true
migration_source: "docs/azents/adr/0075-agent-session-runtime-ownership-removal.md"
---

# Remove AgentSession Runtime Ownership Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `ownership-260625`
- Source: `docs/azents/adr/ownership-260625-ownership-removal.md`
- Historical source date basis: `2026-06-25`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[primary-260625/ADR](../adr/primary-260625-primary-sessions.md) defines `AgentSession` and `AgentRuntime` as sibling models owned by `Agent`.
Phase 3 introduced team primary session semantics, but the implementation still retained an
`agent_sessions.agent_runtime_id` ownership edge and repository methods centered on runtime-owned
active sessions. That kept a hidden global session selector in the runtime model and made future
multi-session support unsafe.

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
