---
title: "Make Model Provider Failures Transparent Historical Requirements Reconstruction"
created: 2026-07-18
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: failures-260718
historical_reconstruction: true
migration_source: "docs/azents/adr/0165-make-model-provider-failures-transparent.md"
---

# Make Model Provider Failures Transparent Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `failures-260718`
- Source: `docs/azents/adr/failures-260718-failures-transparent.md`
- Historical source date basis: `2026-07-18`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently obscures some model-provider failures at the adapter boundary. The OpenAI-native Responses path replaces typed provider terminal errors with generic text such as `Model call failed.` and replaces final SDK failures with `OpenAI Responses request failed.`. LiteLLM and OpenAI paths also map equivalent provider outcomes through different exception families.

This makes provider rejection, authorization failure, quota exhaustion, rate limiting, provider unavailability, and Azents programming failures appear alike. It also prevents the failed-run retry lifecycle, terminal history, frontend, and operational telemetry from preserving the safe reason that explains the failure.

The existing security boundary remains necessary: Azents must not expose raw provider bodies, serialized SDK exceptions, credentials, headers, request input, model output, stack traces, request or response identifiers, or raw streaming frames. However, provider-authored scalar error fields intended to explain a rejected request can be bounded, redacted, and carried safely.

Error transparency cannot be implemented only at final presentation. A provider failure may pass through adapter normalization, automatic compaction, model-turn retry, worker handover, terminal failed-run finalization, and frontend resync. Retry ownership and lifecycle must preserve one safe typed failure through all of those boundaries.

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
