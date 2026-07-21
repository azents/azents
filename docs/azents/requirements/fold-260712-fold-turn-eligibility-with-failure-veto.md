---
title: "Fold Turn Eligibility with Failure Veto Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: fold-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0133-fold-turn-eligibility-with-failure-veto.md"
---

# Fold Turn Eligibility with Failure Veto Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `fold-260712`
- Source: `docs/azents/adr/fold-260712-fold-turn-eligibility-with-failure-veto.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Turn continuation depends both on the context in which buffer draining begins and on the ordered outcomes of individual buffer items. A preparation-only success such as a worktree setup must not start a new turn by itself, but it also must not stop an already active run between turns. A handled failure has different semantics: when it is the final effective outcome, no next turn should start.

A single `turn_eligible: bool` cannot distinguish a neutral preparation success from a failure veto because both would otherwise be `false`.

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
