---
title: "Archived Session Retention and Durable Purge Historical Requirements Reconstruction"
created: 2026-07-19
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: archived-260719
historical_reconstruction: true
migration_source: "docs/azents/adr/0171-archived-session-retention-and-purge.md"
---

# Archived Session Retention and Durable Purge Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `archived-260719`
- Source: `docs/azents/adr/archived-260719-archived-retention-and-purge.md`
- Historical source date basis: `2026-07-19`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[archive-260626/ADR](../adr/archive-260626-archive-policy.md) introduced AgentSession archive as a soft transition for inactive non-primary sessions. It intentionally omitted an archived-session browser and restore flow, and it did not define a retention deadline. Archived session data therefore remains indefinitely unless the existing public hard-delete API is called.

The SessionAgent tree model introduced after [archive-260626/ADR](../adr/archive-260626-archive-policy.md) gives a root AgentSession ownership of child and nested SessionAgent nodes and their linked child AgentSessions. A retention policy must delete this ownership tree as one unit rather than treating only the visible root session as the lifecycle boundary.

Session deletion also crosses external-resource boundaries. ModelFiles, Artifacts, and ExchangeFiles have physical object-storage blobs, and Azents-owned Git worktrees have filesystem and Git branch state whose ownership metadata is stored under the shared SessionAgentContext. Deleting AgentSession rows first can erase the durable metadata needed to finish or retry external cleanup.

ExchangeFile upload currently begins before a new AgentSession necessarily exists, and current rows are workspace/Agent-scoped. However, an ExchangeFile is not intended to be reused across independent root sessions. This requires an explicit retention owner that can be assigned when the first input is accepted without preventing pre-session uploads.

The product direction is that archive is reversible temporary removal, while expiration is the only ordinary permanent-deletion path.

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
