---
title: "Make the events Table the Single Source of Truth and Remove session_items_oai Historical Requirements Reconstruction"
created: 2026-04-28
implemented: 2026-04-28
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: events-260428
historical_reconstruction: true
migration_source: "docs/azents/adr/0003-events-table-as-single-truth.md"
---

# Make the events Table the Single Source of Truth and Remove session_items_oai Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `events-260428`
- Source: `docs/azents/adr/events-260428-events-table-as-truth.md`
- Historical source date basis: `2026-04-28`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

During the OpenAI Agents SDK migration (18-PR stack, #3050-3098), a new `session_items_oai` table was introduced to persist raw SDK `TResponseInputItem` dictionaries. However, the existing `events` table was also dual-written, splitting the two stores in the following ways:

- **Duplicate storage**: the same conversation is stored in two places and two forms, parsed versus raw.
- **Permission split**: the SDK only understands its own history, while domain metadata such as compaction status, subagent boundaries, and observation masking exists only in `events`.
- **Turn definition split**: `turn_id` column in `session_items_oai` versus `TurnCompleteEvent` rows in `events`.
- **Compaction meaning split**: persistent model of deleting event rows and inserting a summary versus in-memory input replacement.
- **Data round-trip loss risk**: responsibility for synchronizing two representations is unclear.

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

- SDK + LiteLLM cross-model normalization is at least as good as our normalization layer. Verify with integration tests in Phase 11 testenv.
- SDK `add_items` dedup-by-id works correctly, preserving ids and avoiding `FAKE_RESPONSES_ID`. Verify with unit tests.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
