---
title: "Move Memory Storage from Filesystem to PostgreSQL Historical Requirements Reconstruction"
created: 2026-04-26
implemented: 2026-04-26
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: memory-260426
historical_reconstruction: true
migration_source: "docs/azents/adr/0002-memory-filesystem-to-db.md"
---

# Move Memory Storage from Filesystem to PostgreSQL Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `memory-260426`
- Source: `docs/azents/adr/memory-260426-memory-filesystem-to-db.md`
- Historical source date basis: `2026-04-26`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

nointern's Memory system stores memories as Markdown files on the EFS filesystem: a `MEMORIES.md` index plus individual `{type}_{topic}.md` files. The model directly modifies those files through existing file tools such as write, edit, read, and delete.

This structure has the following problems:

1. **Concurrency**: If multiple sessions of the same agent edit `MEMORIES.md` at the same time, last-write-wins can lose data.
2. **No atomicity**: Saving a memory is a two-step operation, file write plus index edit. If the operation fails in the middle, orphan files can remain.
3. **EFS dependency**: This blocks the SDK Workspace direction introduced in Discussion #3011.

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
