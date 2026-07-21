---
title: "Filesystem Skill Projection Revisions Historical Requirements Reconstruction"
created: 2026-07-01
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: filesystem-260701
historical_reconstruction: true
migration_source: "docs/azents/adr/0087-filesystem-skill-projection-revisions.md"
---

# Filesystem Skill Projection Revisions Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `filesystem-260701`
- Source: `docs/azents/adr/filesystem-260701-filesystem-skill-projection-revisions.md`
- Historical source date basis: `2026-07-01`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents removed the legacy Skill system before the current Agent Runtime, Agent Workspace, and session-owned Project model stabilized. Skill support is now being reintroduced in a system where three constraints are important at the same time:

1. Skills must be authored and owned as filesystem packages, not as primary DB records.
2. The Agent Runtime is not guaranteed to be running or reachable when a session loop needs to prepare model input.
3. Skill availability is rendered into model-visible prompt/toolkit state, so non-deterministic refreshes can break provider prompt-cache locality.

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-45) reserves the chat input/action-message shape for a future Skill Turn Action:

```json
{
  "action": { "type": "skill", "skill_id": "review-pr" },
  "message": "Review PR #112"
}
```

This ADR records how Skill source, projection, refresh, and runtime/session-loop boundaries should work before implementing the Skill Turn Action and `load_skill` behavior.

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

Current Azents has:

- Agent-owned long-lived Runtime / Agent Workspace state;
- session-owned Project registrations under the Agent Workspace;
- explicit Project selection at new-session time;
- runtime-gated folder browsing for selecting/registering Projects;
- session-scoped Toolkit State patterns;
- deterministic tool catalog and toolkit prompt rules from [deterministic-260628/ADR](../adr/deterministic-260628-deterministic-catalog-and-mcp-snapshots.md);
- `ActionMessagePayload` and a reserved `SkillAction` variant from [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-46).

The current Project model is path-boundary based. There is no current public Project Source, archive bootstrap, Manifest entry, or Project materialization model. Skill discovery must therefore start from explicit filesystem conventions under the Agent Workspace and registered Project paths.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
