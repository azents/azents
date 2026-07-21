---
title: "Reorder Model Input by Logical Event Order After Compaction Historical Requirements Reconstruction"
created: 2026-05-30
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: compaction-260530
historical_reconstruction: true
migration_source: "docs/azents/adr/0042-compaction-logical-event-ordering.md"
---

# Reorder Model Input by Logical Event Order After Compaction Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `compaction-260530`
- Source: `docs/azents/adr/compaction-260530-compaction-logical-event-ordering.md`
- Historical source date basis: `2026-05-30`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Canonical runtime auto compaction is intended to compress old transcript into a summary while preserving recent tail events verbatim. However, the existing implementation appends the compaction summary to the end of the append-only log and moves `model_input_head_event_id` to the summary event. Model input lookup simply reads events after head in id order, so preserved tail events that were physically before the summary can disappear from model input from the next turn onward.

Solving this in lookup logic with branches such as `if compaction summary then recombine events after covered_until_event_id` would make turn construction and model input construction aware of compaction implementation details. Long-running agents add more paths such as resume, retry, reload, manual compaction, auto compaction, and subagent, so such branches are bad for maintainability and correctness.

Also, if the summary includes preserved tail content and the same tail appears again verbatim, duplicate knowledge enters model input. This wastes tokens and makes it harder to judge the latest state when summary and verbatim tail slightly disagree.

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
