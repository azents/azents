---
title: "Precreate the Inherited First Subagent Run Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: precreate-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0119-precreate-inherited-subagent-run.md"
---

# Precreate the Inherited First Subagent Run Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `precreate-260710`
- Source: `docs/azents/adr/precreate-260710-precreate-inherited-subagent.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[subagent-260710/ADR](../adr/subagent-260710-subagent-parent-profile-inheritance.md) requires a newly spawned subagent's first run to inherit the parent AgentRun's exact requested target, resolved model snapshot, and effective reasoning effort without re-routing. The inheritance must be durable before child wake-up. Storing a physical snapshot on InputBuffer would violate its requested-intent boundary, while using temporary AgentSession fields would duplicate AgentRun provenance and require separate consume/clear recovery logic.

[provenance-260710/ADR](../adr/provenance-260710-inference-provenance.md) establishes AgentRun as the durable owner of requested and resolved execution provenance. The child first run is already known when `spawn_agent` executes inside the parent run.

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
