---
title: "Run-Scoped Azents Virtual Filesystem for Managed Skills and Resources Historical Requirements Reconstruction"
created: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: bundled-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0168-release-bundled-and-provider-backed-skill-sources.md"
---

# Run-Scoped Azents Virtual Filesystem for Managed Skills and Resources Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `bundled-260719`
- Source: `docs/azents/adr/bundled-260719-bundled-and-backed-skill-sources.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[filesystem-260701/ADR](../adr/filesystem-260701-filesystem-skill-projection-revisions.md) introduced filesystem-authored Agent and Project Skill packages and session-scoped Skill projection revisions. The current implementation scans the Agent Workspace and registered Project paths, stores complete `SKILL.md` snapshots in session-bound Toolkit State, and uses an adopted projection for prompt rendering, Skill actions, and `load_skill`.

Azents also needs files that are managed outside the Agent Runtime filesystem:

- release-bundled global Skills;
- release-bundled Skills owned by Toolkit Providers;
- future Workspace-managed or catalog-published Skills;
- future Azents-managed references, templates, scripts, assets, or other file-oriented resources.

Representing each new source as a Skill-specific body field would make package resources inaccessible and would require another content contract for every future use case. Copying every managed package into each Agent Runtime would make availability depend on Runtime allocation, duplicate immutable release content, and still leave future DB- or object-storage-backed sources with a separate path.

Azents therefore needs one generalized, read-only virtual filesystem that projects eligible managed files into a stable URI namespace for each run.

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
