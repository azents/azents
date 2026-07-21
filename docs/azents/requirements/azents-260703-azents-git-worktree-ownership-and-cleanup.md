---
title: "Azents-Owned Git Worktree Ownership and Cleanup Historical Requirements Reconstruction"
created: 2026-07-03
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: azents-260703
historical_reconstruction: true
migration_source: "docs/azents/adr/0092-azents-owned-git-worktree-ownership-and-cleanup.md"
---

# Azents-Owned Git Worktree Ownership and Cleanup Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `azents-260703`
- Source: `docs/azents/adr/azents-260703-azents-git-worktree-ownership-and-cleanup.md`
- Historical source date basis: `2026-07-03`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents sessions can currently register explicit Project paths under the Agent Workspace. Those Project rows define prompt/tool Project scope, but they do not mean Azents created, owns, or may delete the underlying filesystem path.

The new worktree flow creates an isolated Git worktree for a new non-primary AgentSession from an explicit source Project and starting ref. The created worktree should become the session Project after setup succeeds and should be removed when the session is archived or deleted.

This introduces destructive cleanup behavior. Cleanup safety must be based on explicit ownership records, not on arbitrary path prefixes, Project rows, or catalog entries.

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
