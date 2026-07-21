---
title: "Workspace Project Browser Surface Historical Requirements Reconstruction"
created: 2026-07-03
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: browser-260703
historical_reconstruction: true
migration_source: "docs/azents/adr/0089-workspace-project-browser-surface.md"
---

# Workspace Project Browser Surface Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `browser-260703`
- Source: `docs/azents/adr/browser-260703-browser-surface.md`
- Historical source date basis: `2026-07-03`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents already distinguishes organization-level Workspace from the Agent Workspace filesystem reported by the runtime provider. Agent Workspace file management exists as a runtime-backed browser rooted at the provider-reported Agent Workspace path, while session-owned Projects exist as exact path registrations under `/workspace/agent`.

[registry-260625/ADR](../adr/registry-260625-registry.md) made Project registrations session-owned. [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-58) made new-session Project selection explicit: the selected Project chips are the exact `project_paths` used to create the new `AgentSession`, and session creation no longer copies hidden Projects from the team-primary session.

The current user interface still exposes Projects as a separate session tab/page and exposes the runtime file browser as an Agent Workspace root-first surface. That creates product and safety issues:

- users work from Projects, but the browser starts at the Agent Workspace root;
- Project management is split from the file browser even though both describe the same runtime workspace;
- Project root nodes need registry-level actions, while ordinary filesystem nodes need file actions;
- an empty Project set must be explicit instead of silently falling back to the Agent Workspace root;
- legacy `?page=projects` routing keeps a Projects page as a peer surface after Project management has moved into Workspace.

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
