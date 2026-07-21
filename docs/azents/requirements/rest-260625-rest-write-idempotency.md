---
title: "Session-Owned REST Write Idempotency Historical Requirements Reconstruction"
created: 2026-06-25
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: rest-260625
historical_reconstruction: true
migration_source: "docs/azents/adr/0077-session-owned-rest-write-idempotency.md"
---

# Session-Owned REST Write Idempotency Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `rest-260625`
- Source: `docs/azents/adr/rest-260625-rest-write-idempotency.md`
- Historical source date basis: `2026-06-25`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[primary-260625/ADR](../adr/primary-260625-primary-sessions.md) makes `AgentSession` the conversation boundary. [ownership-260625/ADR](../adr/ownership-260625-ownership-removal.md) removes runtime ownership from
`AgentSession`, and [registry-260625/ADR](../adr/registry-260625-registry.md) moves the project registry to session ownership. The remaining REST chat
write idempotency table still uses `agent_runtime_id` as part of its durable uniqueness scope.

Runtime-scoped REST write idempotency conflicts with URL-selected sessions because an idempotency key
is a property of a session write boundary, not a physical runtime workspace. Keeping runtime in the
idempotency key would preserve hidden runtime-global write state after session ownership has moved to
`AgentSession`.

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
