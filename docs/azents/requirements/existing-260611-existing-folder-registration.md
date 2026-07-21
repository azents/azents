---
title: "Session Workspace Project Existing Folder Registration Historical Requirements Reconstruction"
created: 2026-06-11
implemented: 2026-06-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: existing-260611
historical_reconstruction: true
migration_source: "docs/azents/design/session-workspace-project-existing-folder-registration.md"
---

# Session Workspace Project Existing Folder Registration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `existing-260611`
- Source: `docs/azents/design/existing-260611-existing-folder-registration.md`
- Historical source date basis: `2026-06-11`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The existing Session Workspace Project design included Project boundary registry and Project Source-based provisioning in the same MVP scope. As a result, Project Source archive upload, empty folder bootstrap, `loaded=false` pending load, Runtime Runner pull/ACK, source object lifecycle, and loading/failed UI state were all needed at once.

The core thing the product needs now is to explicitly mark a specific folder inside Agent Workspace as Project boundary. Project boundary is used for project-scoped `AGENTS.md`, future skill discovery, and registered project guidance in prompt. Provisioning such as file creation, archive extract, and git clone is separate from this boundary problem.

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
