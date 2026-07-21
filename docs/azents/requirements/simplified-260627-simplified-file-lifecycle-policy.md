---
title: "Simplified File Lifecycle Policy Historical Requirements Reconstruction"
created: 2026-06-27
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: simplified-260627
historical_reconstruction: true
migration_source: "docs/azents/adr/0080-simplified-file-lifecycle-policy.md"
---

# Simplified File Lifecycle Policy Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `simplified-260627`
- Source: `docs/azents/adr/simplified-260627-simplified-file-lifecycle-policy.md`
- Historical source date basis: `2026-06-27`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[file-260601/ADR](../adr/file-260601-file-media-resource-lifecycle.md) separated Attachment, Artifact, FilePart, and ModelFile lifecycles. The implemented follow-up kept three independent cleanup policies:

- ExchangeFile expires by time.
- Artifact expires by run age.
- ModelFile uses persistent run-age lifecycle stages: image degradation, unreachable, deleted.

A later implementation attempt moved those policies into a scheduler, but it preserved the complexity. That still left the scheduler calculating due work across sessions and kept lifecycle rules scattered across resource services, engine filters, lowerers, and run input preparation.

The product direction is simpler:

- ModelFile is only a model-context blob, not original-file storage.
- Artifact and ExchangeFile are temporary file-access resources, not long-term storage.
- Long-running work that needs file bytes should use runtime workspace files when a runtime/file toolkit is available.

This ADR supersedes the Artifact run-age and ModelFile persistent degradation/delete portions of [file-260601/ADR](../adr/file-260601-file-media-resource-lifecycle.md) for future implementation. It does not change [file-260601/ADR](../adr/file-260601-file-media-resource-lifecycle.md)'s separation between Attachment, Artifact, FilePart, and ModelFile, nor the rule that URI is a file-location address rather than an entity id.

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
