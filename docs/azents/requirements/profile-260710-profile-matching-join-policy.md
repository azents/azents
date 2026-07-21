---
title: "Reuse the Active Run Profile for Matching Inputs Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: profile-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0118-current-profile-matching-run-join-policy.md"
---

# Reuse the Active Run Profile for Matching Inputs Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `profile-260710`
- Source: `docs/azents/adr/profile-260710-profile-matching-join-policy.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

While an AgentRun is active, additional FIFO input can arrive with the same requested target label and reasoning effort. The current target implementation is static, but [time-260710/ADR](../adr/time-260710-time-target-resolution.md) intentionally leaves room for a future dynamic router. Re-resolving every matching input during an active run would introduce speculative routing for work that has not started a new run and could produce a physical model different from the active run's immutable profile.

The correct join semantics for a future dynamic router may depend on routing inputs and guarantees that do not exist yet. This feature should not prematurely define those future semantics.

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
