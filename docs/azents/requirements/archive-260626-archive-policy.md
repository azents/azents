---
title: "AgentSession Archive Policy Historical Requirements Reconstruction"
created: 2026-06-26
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: archive-260626
historical_reconstruction: true
migration_source: "docs/azents/adr/0079-agent-session-archive-policy.md"
---

# AgentSession Archive Policy Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `archive-260626`
- Source: `docs/azents/adr/archive-260626-archive-policy.md`
- Historical source date basis: `2026-06-26`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

AgentSession already has an `archived` lifecycle state in the data model, but the product did not expose
an archive action. The Agent-focused sidebar now makes multiple active sessions visible and selectable,
so users need a way to remove obsolete non-primary sessions from the active list without deleting the
durable transcript.

The team-primary session has a different role from other sessions: it is the stable default
conversation anchor for an Agent. The `/chat` route and team-primary lookup rely on that anchor to
exist or be created as the default session. Archiving it would make the default conversation feel
replaceable and would require replacement-session semantics that are easy to confuse with ordinary
session cleanup.

Running sessions also have active worker, live projection, WebSocket, and pending input state. Archiving
them while they are running would introduce ambiguous ordering between stop intent, worker completion,
and session lifecycle changes.

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
