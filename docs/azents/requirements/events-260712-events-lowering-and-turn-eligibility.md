---
title: "Separate Durable Events, Model Lowering, and Turn Eligibility Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: events-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0132-separate-durable-events-model-lowering-and-turn-eligibility.md"
---

# Separate Durable Events, Model Lowering, and Turn Eligibility Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `events-260712`
- Source: `docs/azents/adr/events-260712-events-lowering-and-turn-eligibility.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Input-buffer preparation can produce durable events for UI, audit, recovery, or model context. Event persistence does not by itself imply that the event is model-facing: the event lowerer explicitly drops UI-only event kinds. Likewise, producing a durable or model-facing event does not by itself define whether the buffer-drain cycle should start a turn.

Conflating these concerns makes action-specific UI events accidentally control model input or run creation.

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
