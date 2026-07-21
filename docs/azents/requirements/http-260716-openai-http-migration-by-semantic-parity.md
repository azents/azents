---
title: "Define the OpenAI HTTP Migration by Semantic Parity Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: http-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0148-define-openai-http-migration-by-semantic-parity.md"
---

# Define the OpenAI HTTP Migration by Semantic Parity Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `http-260716`
- Source: `docs/azents/adr/http-260716-openai-http-migration-by-semantic-parity.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-103) establishes an OpenAI-native Responses transport family and requires migrating OpenAI HTTP calls to the official SDK before introducing WebSocket transport. A migration completion contract is needed because the current LiteLLM and future OpenAI SDK paths do not produce byte-identical wire requests or response objects.

Treating LiteLLM's transformed wire representation as the target would copy an intermediary's incidental behavior into the new OpenAI lowerer. Migrating only primary Agent sampling would instead leave OpenAI request semantics split between the new adapter and the shared LiteLLM Responses helper used by context compaction and automatic Session title generation.

The stable contract must cover product-visible behavior and existing run lifecycle invariants while allowing the OpenAI-native path to represent the same semantics in the official SDK's types.

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
