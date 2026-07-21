---
title: "User Input Boundary FilePart Materialization Historical Requirements Reconstruction"
created: 2026-06-04
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: input-260604
historical_reconstruction: true
migration_source: "docs/azents/adr/0049-user-input-bound-filepart-materialization.md"
---

# User Input Boundary FilePart Materialization Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `input-260604`
- Source: `docs/azents/adr/input-260604-input-bound-filepart-materialization.md`
- Historical source date basis: `2026-06-04`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[exchange-260531/ADR](../adr/exchange-260531-exchange-uploads.md) decided to change Web upload to agent-scoped Exchange upload instead of session-scoped upload. [file-260601/ADR](../adr/file-260601-file-media-resource-lifecycle.md) separated Attachment, Artifact, FilePart, and ModelFile lifecycles. However, current implementation mixes these boundaries again:

- Upload API returns both Exchange attachment and `file_part`.
- Frontend stores `file_part` from upload response and sends it again as `file_parts` in WebSocket message payload.
- Backend chat request trusts client-provided `file_parts` and puts them into user input.
- Exchange attachment resolution globally looks up object key first, then checks only workspace membership.
- ModelFile lookup also queries by ID without current agent namespace.

This creates two problems.

First, upload and user input creation have different lifecycles. Upload creates an Exchange attachment in an agent namespace, and session or user input may not exist yet. FilePart, on the other hand, is an abstraction for model input content part and should be created only when user input is created.

Second, file identity is interpreted outside agent namespace. If agent A/B in the same workspace reference the same `exchange://...` string or `model_file_id`, global lookup followed by only workspace permission check can cause cross-agent leakage. This cannot be solved by a permission-denied hotfix. Resolution must not see outside the current agent at namespace resolution stage.

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
