---
title: "Display Context Usage from the Resolved Run Profile Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: context-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0114-run-scoped-context-usage-display.md"
---

# Display Context Usage from the Resolved Run Profile Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `context-260710`
- Source: `docs/azents/adr/context-260710-context-usage-display.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The chat header currently combines observed token usage with context-window and compaction values derived from the Agent default model. Per-prompt model selection allows a session to execute with a different resolved model, so retaining the Agent default as the denominator would produce a misleading percentage.

A queued input or Composer selection is only target intent. It has not yet been resolved and must not be presented as the model that produced observed usage.

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
