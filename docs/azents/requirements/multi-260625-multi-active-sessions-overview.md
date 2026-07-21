---
title: "Multi-Active AgentSession Migration Overview Historical Requirements Reconstruction"
created: 2026-06-25
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: multi-260625
historical_reconstruction: true
migration_source: "docs/azents/design/multi-active-agent-sessions-overview.md"
---

# Multi-Active AgentSession Migration Overview Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `multi-260625`
- Source: `docs/azents/design/multi-260625-multi-active-sessions-overview.md`
- Historical source date basis: `2026-06-25`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents is moving toward an agent-centered model where an `Agent` has one runtime and many sessions. `AgentRuntime` and `AgentSession` are sibling models under `Agent`, not parent/child models. `AgentRuntime` owns the shared runtime workspace and provider lifecycle. `AgentSession` owns conversation, input, and execution-control state.

The current foundation still contains single-current-session assumptions. This document defines the high-level migration direction from that foundation to a model where multiple `AgentSession` rows for the same `Agent` can be open and executable. It is an overview document only. Step-specific schema, API, worker, and UI designs should be documented separately when each migration phase is implemented.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

This overview does not define the full implementation details for:

- Exact database migration DDL for each phase.
- Final public API shape for all session list/focus/create routes.
- Frontend multi-session navigation UX.
- Detailed shared workspace conflict UX and retry behavior.
- Subagent or ephemeral agent spawn semantics.
- Per-session sandbox isolation.

Those topics should be handled in follow-up design documents.

## Non-goals

This overview does not define the full implementation details for:

- Exact database migration DDL for each phase.
- Final public API shape for all session list/focus/create routes.
- Frontend multi-session navigation UX.
- Detailed shared workspace conflict UX and retry behavior.
- Subagent or ephemeral agent spawn semantics.
- Per-session sandbox isolation.

Those topics should be handled in follow-up design documents.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

The current foundation still has these single-current assumptions:

1. `agent_sessions` has a partial unique index on `agent_runtime_id` that allows only one active session for the agent in practice.
2. `agent_runtimes.current_session_id` is used as the current active session pointer.
3. Some service paths resolve writes through the runtime's current active session instead of the explicitly requested `AgentSession`.
4. Reset/new semantics rotate the current session by archiving the old one and creating a new active one.
5. Some user-facing APIs use `active-session` vocabulary.
6. The UI mostly treats the current session as the only writable chat surface for an agent.

These assumptions are compatible with the foundation phase but block true multi-active session execution.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
