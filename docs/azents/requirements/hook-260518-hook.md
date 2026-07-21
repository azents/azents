---
title: "Adopt Runtime Hook System Historical Requirements Reconstruction"
created: 2026-05-18
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: hook-260518
historical_reconstruction: true
migration_source: "docs/azents/adr/0033-runtime-hook-system.md"
---

# Adopt Runtime Hook System Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `hook-260518`
- Source: `docs/azents/adr/hook-260518-hook.md`
- Historical source date basis: `2026-05-18`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[toolkit-260514/ADR](../adr/toolkit-260514-toolkit-hooks-for-agents-md.md) introduced Toolkit hooks and Toolkit State with AGENTS.md loading as the first consumer. That decision enabled tool-call observation and provider-owned state/prompt updates, but it did not finalize a general hook taxonomy for the whole runtime across session, run, turn, tool, and sandbox lifecycle.

Beyond AGENTS.md, nointern runtime needs providers to observe runtime lifecycle or initialize, clean up, and compact their owned state. For example, providers may prepare state at first session start, inject additional user prompt at turn start, perform policy-like deny before tool calls, and sync provider-owned state on sandbox hibernate/restore. If these needs are added as branches in individual code paths, hook authors get a complex mental model and runtime adapter accumulates provider-specific special logic.

At the same time, external plugin runtime, model-call interception, and arbitrary mutation/continuation framework are larger and riskier than current needs. Therefore, keep the current Toolkit boundary as provider boundary, while acknowledging that the name may more accurately become runtime capability provider long term, and define a simple runtime hook system.

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
