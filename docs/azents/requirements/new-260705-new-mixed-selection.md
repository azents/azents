---
title: "New Session Mixed Workspace Selection Historical Requirements Reconstruction"
created: 2026-07-05
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: new-260705
historical_reconstruction: true
migration_source: "docs/azents/adr/0093-new-session-mixed-workspace-selection.md"
---

# New Session Mixed Workspace Selection Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `new-260705`
- Source: `docs/azents/adr/new-260705-new-mixed-selection.md`
- Historical source date basis: `2026-07-05`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-59) established explicit new-session Project selection: the selected Project UI equals the
Project bindings created for the new session, and reusable Project presets are convenience paths rather
than canonical Project identities.

[initialization-260703/ADR](../adr/initialization-260703-initialization-lifecycle.md) introduced a durable session initialization lifecycle that gates first-run dispatch while
startup work is pending. [azents-260703/ADR](../adr/azents-260703-azents-git-worktree-ownership-and-cleanup.md) introduced Azents-owned Git worktrees as session-owned generated
Projects with explicit ownership and cleanup metadata.

The first implemented worktree UI split new-session setup into a global workspace mode:

- `existing_projects`: multiple existing Project paths;
- `git_worktree`: one source Project and one starting ref.

That global mode is not the intended product model. Users need to assemble a new session workspace as
a list of items, where normal Projects and Git worktree requests can be mixed in one session. The UI
must preserve the existing compact Project selector flow instead of introducing a separate Project
selection screen.

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
