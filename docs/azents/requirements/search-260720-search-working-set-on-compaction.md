---
title: "Reset the Tool Search Working Set on Successful Compaction Historical Requirements Reconstruction"
created: 2026-07-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: search-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0172-reset-tool-search-working-set-on-compaction.md"
---

# Reset the Tool Search Working Set on Successful Compaction Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `search-260720`
- Source: `docs/azents/adr/search-260720-search-working-set-on-compaction.md`
- Historical source date basis: `2026-07-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-185) established a session-scoped Tool Search working set that survives context compaction. That policy preserves capability recency across the entire AgentSession, but compaction is also the explicit boundary where Azents replaces the model-visible conversation history with a new durable checkpoint.

Keeping deferred-tool activation across that boundary can expose tools selected for details that no longer remain in the active model context. The compacted model should rediscover deferred capabilities from the checkpoint and subsequent user intent instead of inheriting an unbounded pre-compaction relevance history.

The working set is stored as the `tool_search/working_set` session-bound Toolkit State. Other Toolkit State in the same AgentSession includes independent durable state such as Todo, Goal, and MCP tool snapshots and must not be reset with Tool Search recency.

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
