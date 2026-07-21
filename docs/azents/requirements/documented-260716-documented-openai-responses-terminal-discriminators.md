---
title: "Use Documented OpenAI Responses Terminal Discriminators Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: documented-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0160-use-documented-openai-responses-terminal-discriminators.md"
---

# Use Documented OpenAI Responses Terminal Discriminators Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `documented-260716`
- Source: `docs/azents/adr/documented-260716-documented-openai-responses-terminal-discriminators.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[official-260716/ADR](../adr/official-260716-official-openai-sdk-stream-events.md) requires OpenAI-native stream handlers to match both the official SDK class and its documented wire discriminator. [failure-260716/ADR](../adr/failure-260716-openai-http-failure-semantics-at-the-azents-boundary.md) lists `response.failed`, `response.incomplete`, `error`, and `response.error` as typed failure events.

Validation against the pinned OpenAI Python SDK 2.45.0 found that its `ResponseStreamEvent` union contains:

- `ResponseFailedEvent` with `type="response.failed"`;
- `ResponseIncompleteEvent` with `type="response.incomplete"`;
- `ResponseErrorEvent` with `type="error"`.

The pinned union does not define a typed `response.error` discriminator. Treating an incidental loose SDK fallback class carrying that unknown discriminator as `ResponseErrorEvent` would violate [official-260716/ADR](../adr/official-260716-official-openai-sdk-stream-events.md)'s class-and-wire-type guard.

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
