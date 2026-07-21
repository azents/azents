---
title: "Split FunctionCallItem.output into a Separate FunctionCallOutputItem Historical Requirements Reconstruction"
created: 2026-04-29
implemented: 2026-04-29
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: function-260429
historical_reconstruction: true
migration_source: "docs/azents/adr/0004-split-function-call-output-item.md"
---

# Split FunctionCallItem.output into a Separate FunctionCallOutputItem Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `function-260429`
- Source: `docs/azents/adr/function-260429-function-call-output-item.md`
- Historical source date basis: `2026-04-29`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

This follows [events-260428/ADR](../adr/events-260428-events-table-as-truth.md), which made the events table the single source of truth. Once the events table was defined as a row-per-event schema with `type/data/raw_data/external_id`, only `FunctionCallItem` in `SessionEvent` had an impedance mismatch:

- `FunctionCallItem(output: FunctionCallOutput | None)` — existing nested structure. The call and result are tied together in one dataclass.
- Events table row-per-event — represents the call and result as two rows, which is already how SDK Runner `add_items` flows.

Because of this mismatch, `EventStoreV2` needed a conversion layer: split one `FunctionCallItem` into two rows on write, and merge two rows back into one item on read. If a tool was interrupted by worker shutdown, the system also had to write the same `FunctionCallItem` again in update mode with `output=None` (`emit.update()`, `EventStore.set_function_call_output`), breaking the append-only model.

Affected sites: `engine/types.py`, `engine/emit.py`, `engine/sdk/event_converter.py`, `engine/engine.py`, `engine/context.py`, `repos/message/store.py`, `broker/serialization.py`, plus four test files. Roughly 21 sites directly referenced nested output.

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
