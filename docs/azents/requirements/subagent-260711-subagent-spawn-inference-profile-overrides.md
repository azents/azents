---
title: "Allow Explicit Inference Profiles When Spawning Subagents Historical Requirements Reconstruction"
created: 2026-07-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: subagent-260711
historical_reconstruction: true
migration_source: "docs/azents/adr/0124-subagent-spawn-inference-profile-overrides.md"
---

# Allow Explicit Inference Profiles When Spawning Subagents Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `subagent-260711`
- Source: `docs/azents/adr/subagent-260711-subagent-spawn-inference-profile-overrides.md`
- Historical source date basis: `2026-07-11`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[subagent-260710/ADR](../adr/subagent-260710-subagent-parent-profile-inheritance.md) requires a newly spawned subagent to inherit the complete effective inference profile of the concrete parent `AgentRun`. This keeps the child on the same resolved physical model and reasoning effort instead of falling back to Agent defaults or re-resolving the parent's target.

Some delegated tasks benefit from a different Agent-owned model target or reasoning effort. The existing `spawn_agent` contract cannot express that intent. Any extension must preserve parent-run inheritance as the default, use the existing label-based target boundary, respect forked-context continuity, and avoid creating an unusable child when the requested profile is invalid.

Predefined subagent profiles and per-follow-up profile overrides are not part of the current product contract and are outside this decision.

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
