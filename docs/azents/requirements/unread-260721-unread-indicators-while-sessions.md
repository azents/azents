---
title: "Suppress Unread Indicators While Sessions Run Historical Requirements Reconstruction"
created: 2026-07-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: unread-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0181-suppress-unread-indicators-while-sessions-run.md"
---

# Suppress Unread Indicators While Sessions Run Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `unread-260721`
- Source: `docs/azents/adr/unread-260721-unread-indicators-while-sessions.md`
- Historical source date basis: `2026-07-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-202) established a durable Session-shared unread boundary for terminal Run results. A Session can begin a newer Run before an older terminal result is reviewed, so the durable unread boundary and `run_state = running` can coexist.

Showing both the running spinner and unread dot in the Agent rail made active work appear to be an unread completed result. In normal use, queued or follow-up work made this combination frequent enough to obscure the intended attention signal.

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
