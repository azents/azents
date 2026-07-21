---
title: "Adopt Tool Output Context-pressure Filter Historical Requirements Reconstruction"
created: 2026-06-04
implemented: 2026-06-04
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: output-260604
historical_reconstruction: true
migration_source: "docs/azents/adr/0048-tool-output-context-pressure-filter.md"
---

# Adopt Tool Output Context-pressure Filter Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `output-260604`
- Source: `docs/azents/adr/output-260604-output-context-pressure-filter.md`
- Historical source date basis: `2026-06-04`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents removed the existing `CanonicalObservationMaskingFilter`. That filter directly stored shortened old `ClientToolResultPayload` output in canonical DB payload. This meant model input optimization could cause durable history loss, and compaction summary could see already degraded tool output.

Codex benchmarking showed that tool/function output context trimming is better treated as model-facing input shaping, not raw/canonical history mutation. In particular, under context pressure, tool output body is replaced by a placeholder while preserving call id, status, and metadata.

Azents already has abnormal output defenses per tool: bash stdout/stderr truncation, grep match limit, Discord output limit, AGENTS content truncation, and post-lower `NativeRequestSizeGuard`. Therefore, this decision is not about introducing a new per-output cap; it is about handling context pressure when an otherwise normal transcript accumulates and exceeds the overall model input context budget.

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
