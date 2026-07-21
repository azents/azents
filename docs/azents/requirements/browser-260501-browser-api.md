---
title: "Add Session Sandbox Workspace Browser API Historical Requirements Reconstruction"
created: 2026-05-01
implemented: 2026-05-02
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: browser-260501
historical_reconstruction: true
migration_source: "docs/azents/adr/0005-workspace-browser-api.md"
---

# Add Session Sandbox Workspace Browser API Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `browser-260501`
- Source: `docs/azents/adr/browser-260501-browser-api.md`
- Historical source date basis: `2026-05-01`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The NoIntern web chat screen had an existing file exploration UX based on `session-data`, but that feature was not a browser for the `/home/sandbox` runtime filesystem. What users expect is to browse the actual `/home/sandbox` root that the session sandbox sees, then read and download files created by the agent directly from the Web UI.

Problems in the existing structure:

- `session-data` is an upload/attachment store and is not the source of truth for the sandbox working directory.
- The existing `SessionExplorer` is an auxiliary modal UX, making it hard to evolve into a workspace panel next to the chat screen.
- If sandbox lifecycle becomes visible lazily only through shell tool calls, users cannot easily understand why the browser is empty.

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
