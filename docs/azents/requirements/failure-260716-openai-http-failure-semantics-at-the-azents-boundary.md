---
title: "Keep OpenAI HTTP Failure Semantics at the Azents Boundary Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: failure-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0157-keep-openai-http-failure-semantics-at-the-azents-boundary.md"
---

# Keep OpenAI HTTP Failure Semantics at the Azents Boundary Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `failure-260716`
- Source: `docs/azents/adr/failure-260716-openai-http-failure-semantics-at-the-azents-boundary.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The official OpenAI SDK supplies typed HTTP, connection, timeout, status, and streaming event failures. Its exception strings and response objects may contain provider response bodies or request identifiers. Propagating those exceptions directly would make sampling, compaction, and automatic Session title behavior depend on SDK presentation details and could expose data that Azents does not log or persist.

Azents already owns model-call connection configuration, parsed-event idle and absolute attempt deadlines, User Stop priority, stream cleanup, terminal event requirements, failed-run classification, and user-safe failure messages. The transport migration should preserve those product boundaries while replacing LiteLLM-specific exception handling with official SDK types.

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
