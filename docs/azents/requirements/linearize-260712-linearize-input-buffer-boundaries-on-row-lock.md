---
title: "Linearize Input Buffer Boundaries on the Session Row Lock Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: linearize-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0137-linearize-input-buffer-boundaries-on-session-row-lock.md"
---

# Linearize Input Buffer Boundaries on the Session Row Lock Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `linearize-260712`
- Source: `docs/azents/adr/linearize-260712-linearize-input-buffer-boundaries-on-row-lock.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Sequential buffer preparation requires a deterministic boundary between accepting another input and starting or continuing a turn. Without a shared database serialization point, a producer can insert a new buffer after the worker observes an empty queue but before it claims the next turn. `FOR UPDATE SKIP LOCKED` also allows a concurrent processor to bypass a locked FIFO head and process a later row first.

Redis worker ownership reduces concurrency but is a lease without a database fencing token. FIFO and empty-boundary correctness must not depend solely on that external ownership assumption.

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
