---
title: "Pyright Configuration Review Historical Requirements Reconstruction"
created: 2026-03-10
implemented: 2026-03-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: pyright-260310
historical_reconstruction: true
migration_source: "docs/azents/design/pyright-config.md"
---

# Pyright Configuration Review Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `pyright-260310`
- Source: `docs/azents/design/pyright-260310-pyright-config.md`
- Historical source date basis: `2026-03-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Unknown — the historical source does not state this explicitly.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

"Strict for our code, pragmatic for libraries"

- Keep `typeCheckingMode = "strict"`.
- Unknown should occur only from libraries without stubs, not from our code (`reportMissingParameterType` and other rules cover our code separately).
- Pyright has no per-library diagnostic suppression feature (confirmed by maintainer erictraut, issue #10566).

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
