---
title: "Bound Model Streams by Parsed-Event Idle and Absolute Attempt Time Historical Requirements Reconstruction"
created: 2026-07-15
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: stream-260715
historical_reconstruction: true
migration_source: "docs/azents/adr/0146-model-stream-parsed-event-idle-and-attempt-bounds.md"
---

# Bound Model Streams by Parsed-Event Idle and Absolute Attempt Time Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `stream-260715`
- Source: `docs/azents/adr/stream-260715-stream-parsed-event-idle-and-attempt-bounds.md`
- Historical source date basis: `2026-07-15`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently has no Azents-owned watchdog that guarantees a model provider attempt will terminate when its stream stalls. Provider and HTTP-library defaults are insufficient as the product-level reliability contract because their timeout boundaries and retry behavior can vary by provider and adapter.

The watchdog must not infer whether an event represents meaningful or semantic progress. Provider event vocabularies differ, hidden reasoning may be legitimate work, and LiteLLM may transform or synthesize events. Azents can reliably observe only whether the adapter yielded another parsed provider event.

The watchdog must preserve the existing stream lifecycle boundaries:

- canonical provider output becomes durable only after completed provider output;
- incomplete tool calls are never admitted or executed;
- explicit User Stop may preserve valid partial assistant text;
- live partial output is non-durable and must hand off without duplication or loss;
- reconnect and REST resynchronization reconstruct current live state.

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
