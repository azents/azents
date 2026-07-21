---
title: "Session Initialization Lifecycle Historical Requirements Reconstruction"
created: 2026-07-03
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: initialization-260703
historical_reconstruction: true
migration_source: "docs/azents/adr/0091-session-initialization-lifecycle.md"
---

# Session Initialization Lifecycle Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `initialization-260703`
- Source: `docs/azents/adr/initialization-260703-initialization-lifecycle.md`
- Historical source date basis: `2026-07-03`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Some AgentSession startup work must happen after a session and its first input are accepted, but before the first agent run begins. Git worktree creation is the motivating case, but the same lifecycle can also cover runtime warmup, credential checks, workspace setup scripts, Project registration, catalog upsert, and catalog status refresh.

Current session creation writes an `AgentSession`, registers explicit `session_workspace_projects`, stores the first input as an `InputBuffer`, publishes pending input live state, and wakes the worker. The worker then promotes input buffers and creates an `agent_runs` row. There is no generic pre-run lifecycle gate.

A one-off worktree-specific gate would duplicate the same concerns for future session startup work and would make UI/live-state behavior inconsistent.

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
