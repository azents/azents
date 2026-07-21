---
title: "Deliver the OpenAI HTTP Migration as One Revertible Change Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: migration-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0161-deliver-openai-http-migration-as-one-revertible-change.md"
---

# Deliver the OpenAI HTTP Migration as One Revertible Change Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `migration-260716`
- Source: `docs/azents/adr/migration-260716-openai-http-migration-as-revertible-change.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[over-260716/ADR](../adr/over-260716-over-openai-http-paths-atomically.md) requires one atomic runtime cutover across OpenAI API-key and ChatGPT OAuth sampling, compaction, and automatic Session title generation. It permits preparatory code to land before the final routing change, provided production does not run split routing.

The required operational rollback is stricter: reverting only the migration pull request must restore the complete preceding LiteLLM implementation. A stacked delivery would require identifying and reverting several dependent pull requests, even if only the final one enabled routing.

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
