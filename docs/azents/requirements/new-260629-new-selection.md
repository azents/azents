---
title: "New Session Project Selection Historical Requirements Reconstruction"
created: 2026-06-29
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: new-260629
historical_reconstruction: true
migration_source: "docs/azents/adr/0086-new-session-project-selection.md"
---

# New Session Project Selection Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `new-260629`
- Source: `docs/azents/adr/new-260629-new-selection.md`
- Historical source date basis: `2026-06-29`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently has session-owned Project registrations. A Project registration is a runtime workspace path associated with an `AgentSession`. New team sessions historically received a snapshot copy of the team-primary session's Projects.

That copy behavior was useful as a bootstrap shortcut, but it is not the intended product model for explicit multi-session work:

- users should be able to decide which Projects a new session uses before sending the first message;
- the Project chips shown in the new-session UI should exactly match the Project registrations that the created session receives;
- the team-primary session should not act as the hidden source of truth for new session Projects;
- nested directories and parent/child Project paths are valid user-selected working scopes;
- Project presets are needed for convenience, but should not become a logical Project/source/materialization model in this phase.

This ADR refines [primary-260625/ADR](../adr/primary-260625-primary-sessions.md) and [registry-260625/ADR](../adr/registry-260625-registry.md) for the first explicit Project-selection step. It does not decide git clone, worktree, Project source, Project trust, or Project-local config behavior.

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
