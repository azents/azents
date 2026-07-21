---
title: "Cut Over OpenAI-Compatible HTTP Paths Atomically Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: over-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0159-cut-over-openai-compatible-http-paths-atomically.md"
---

# Cut Over OpenAI-Compatible HTTP Paths Atomically Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `over-260716`
- Source: `docs/azents/adr/over-260716-over-openai-http-paths-atomically.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The official OpenAI SDK HTTP migration covers OpenAI API-key and ChatGPT OAuth across primary sampling, context compaction, and automatic Session title generation. Routing those six combinations independently would leave temporary production states in which one logical provider uses different request, transport, retry, and error owners depending on the call site.

A runtime fallback from the SDK path to LiteLLM could also submit the same logical model operation through two transports after an ambiguous failure. That would make duplicate generation, tool calls, cost, and failure classification difficult to reason about.

The migration still requires an operational rollback path. A rollback should restore the previously deployed LiteLLM implementation by deploying the preceding code version, without requiring a forward-only data migration or a permanent runtime feature flag.

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
