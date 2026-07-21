---
title: "Scope OpenAI SDK Clients to Logical Model Operations Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: clients-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0156-scope-openai-sdk-clients-to-logical-model-operations.md"
---

# Scope OpenAI SDK Clients to Logical Model Operations Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `clients-260716`
- Source: `docs/azents/adr/clients-260716-openai-sdk-clients-to-logical-operations.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The official `AsyncOpenAI` client owns an HTTP connection pool, base URL, authentication configuration, SDK retry behavior, and transport resources that require explicit closure. Creating a new client for every physical Responses request would discard connection reuse across the multi-turn sampling loop. Sharing clients process-wide would instead require long-lived cache keys and invalidation rules for integration credentials, ChatGPT OAuth access tokens, custom base URLs, and event-loop ownership.

Azents already has logical operation boundaries with stable resolved credentials. Primary sampling runs inside one `AgentRunExecution`; continuation state is also scoped to that execution. Compaction and automatic Session title generation are separate bounded model operations.

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
