---
title: "Keep Agent Main Model as the Default Target Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: target-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0109-agent-default-model-target-role.md"
---

# Keep Agent Main Model as the Default Target Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `target-260710`
- Source: `docs/azents/adr/target-260710-target-role.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Per-prompt model selection moves the active human choice into the composer, but a new AgentSession has no last-used profile until its first run starts. System execution can also begin before a human has selected a profile. Removing the Agent main model setting would therefore require a separate mandatory-selection or system fallback mechanism.

The existing `main_model_label` and Workspace `default_main_model_label` already define deterministic Agent-owned targets. Their product meaning can narrow from the model used for every run to the initial default used before session-specific selection exists.

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
