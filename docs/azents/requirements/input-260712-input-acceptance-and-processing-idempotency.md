---
title: "Separate Input Acceptance and Processing Idempotency Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: input-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0138-separate-input-acceptance-and-processing-idempotency.md"
---

# Separate Input Acceptance and Processing Idempotency Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `input-260712`
- Source: `docs/azents/adr/input-260712-input-acceptance-and-processing-idempotency.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The current input-buffer table accepts an optional idempotency key scoped to `(session_id, kind, idempotency_key)`. REST writes also carry `client_request_id`, and some control operations use `chat_write_requests`. Splitting one user-write contract across these mechanisms allows the same request id to create different buffer kinds and lets a same-kind retry return an existing buffer without validating the full payload.

Input acceptance and processor retry are separate idempotency problems. The producer knows whether two requests represent the same intent, while the processor knows which semantic events and side effects belong to one accepted buffer.

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
