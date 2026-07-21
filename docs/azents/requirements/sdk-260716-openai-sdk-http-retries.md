---
title: "Use Default OpenAI SDK HTTP Retries Historical Requirements Reconstruction"
created: 2026-07-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sdk-260716
historical_reconstruction: true
migration_source: "docs/azents/adr/0155-use-default-openai-sdk-http-retries.md"
---

# Use Default OpenAI SDK HTTP Retries Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sdk-260716`
- Source: `docs/azents/adr/sdk-260716-openai-sdk-http-retries.md`
- Historical source date basis: `2026-07-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The official OpenAI Python SDK retries transient HTTP failures before returning a successful response or final exception to its caller. In the pinned 2.45.0 release, the default `max_retries` value is two, allowing up to three physical HTTP requests for one SDK call.

The retry policy covers transport exceptions and initial HTTP responses including 408, 409, 429, and 5xx. It honors bounded `retry-after-ms` and `retry-after` values and the provider-specific `x-should-retry` override before falling back to exponential backoff with jitter. It does not restart a Responses stream after a successful HTTP response has been returned and stream events have begun.

Azents could disable SDK retries so one application model attempt always maps to one physical HTTP request. That would make request counts exact at the Azents attempt boundary, but it would promote short transport, rate-limit, and server failures into the durable failed-run retry path instead of allowing the official SDK to recover them immediately.

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
