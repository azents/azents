---
title: "ADR-0004: Split FunctionCallItem.output into a Separate FunctionCallOutputItem"
created: 2026-04-29
tags: [architecture, engine, backend]
---

# ADR-0004: Split FunctionCallItem.output into a Separate FunctionCallOutputItem

## Context

This follows ADR-0003, which made the events table the single source of truth. Once the events table was defined as a row-per-event schema with `type/data/raw_data/external_id`, only `FunctionCallItem` in `SessionEvent` had an impedance mismatch:

- `FunctionCallItem(output: FunctionCallOutput | None)` — existing nested structure. The call and result are tied together in one dataclass.
- Events table row-per-event — represents the call and result as two rows, which is already how SDK Runner `add_items` flows.

Because of this mismatch, `EventStoreV2` needed a conversion layer: split one `FunctionCallItem` into two rows on write, and merge two rows back into one item on read. If a tool was interrupted by worker shutdown, the system also had to write the same `FunctionCallItem` again in update mode with `output=None` (`emit.update()`, `EventStore.set_function_call_output`), breaking the append-only model.

Affected sites: `engine/types.py`, `engine/emit.py`, `engine/sdk/event_converter.py`, `engine/engine.py`, `engine/context.py`, `repos/message/store.py`, `broker/serialization.py`, plus four test files. Roughly 21 sites directly referenced nested output.

## Decision

Remove the `output` field from `FunctionCallItem` and introduce a separate `FunctionCallOutputItem(DurableEvent)`. Make `SessionEvent` and events rows natively 1:1 compatible.

```python
@dataclasses.dataclass(frozen=True)
class FunctionCallItem(DurableEvent):
    """Function tool call. One-to-one with FUNCTION_CALL_ITEM in events."""
    id: str
    tool_call: FunctionToolCall
    source_model: str | None
    raw_output: dict[str, object] | None


@dataclasses.dataclass(frozen=True)
class FunctionCallOutputItem(DurableEvent):
    """Function tool execution result. One-to-one with FUNCTION_CALL_OUTPUT_ITEM in events.

    Paired with the :class:`FunctionCallItem` that has the same ``call_id``.
    """
    id: str
    call_id: str
    output: FunctionCallOutput
    source_model: str | None
    raw_output: dict[str, object] | None
```

APIs removed at the same time:

- `EventStore.set_function_call_output(session_id, event_id, output)` — handle `FunctionCallOutputItem` through normal `append([...])`.
- `emit.update(event)` mode — unify on append-only. Emit `durable(FunctionCallOutputItem(...))` instead.

Pending function-call resume logic changes from `FunctionCallItem.output is None` to: find `FunctionCallItem` rows whose `call_id` has no matching `FunctionCallOutputItem` in history (`engine.py:_find_pending_function_calls`).

## Considered Options

### A. Keep status quo: nested `FunctionCallItem(output: FunctionCallOutput | None)`

`EventStoreV2` splits 1 → 2 rows on write and merges 2 rows → 1 item on read.

Reasons rejected:

- A conversion layer remains permanently between the SDK Runner's row-per-event representation and `SessionEvent`.
- `set_function_call_output` and `emit.update()` keep update mode alive, breaking the append-only principle.
- Responsibility for synchronizing the two representations of the same `call_id`—call row and merged item—is distributed.

### B. Split out `FunctionCallOutputItem`, which is this decision

Remove output from `FunctionCallItem` and add a separate dataclass.

Reasons accepted:

- The events_v2 schema matches the SDK Runner row-per-event model, which is already validated.
- `set_function_call_output` API and `emit.update()` mode can both be removed, simplifying code and unifying on append-only.
- Pending function-call detection is naturally expressed as the presence or absence of another row in history, with the DB as the source of truth.

### C. Change events_v2 schema: nest output inside the `FUNCTION_CALL_ITEM` row

Reasons rejected:

- It mismatches the SDK Runner row-per-event model, requiring conversion in two places for SDK `add_items` expressions.
- It breaks the validated SDK design to fit our domain model.

## Consequences

### Positive

- `SessionEvent` and events rows become natively 1:1 compatible, removing the conversion layer.
- Append-only consistency is restored by removing `EventStore.set_function_call_output` and `emit.update()`.
- Pending function-call detection is unified as a history check with the DB as the single source of truth.
- SDK Runner `add_items` passes through as-is, so worker and SDK paths use the same representation.

### Negative

- Large diff across roughly 21 sites. Because `SessionEvent` core types change, broker serialization, store, context masking, engine resume, event_converter, and related code all need updates.
- Callers must handle pairing directly through `call_id`. Code such as `mask_observations` and `find_compaction_boundary` must branch separately on `FunctionCallOutputItem`.

## When Alternatives Were Discarded

The conversion layer in option A was removed in Phase 1 of the events unification stack. The schema mismatch in option C was never adopted because the events_v2 schema is tied to ADR-0003's row-per-event decision.

## References

- Design: [`design/events-unification-2026-04-29.md`](../design/events-unification-2026-04-29.md) §DP1
- ADR-0003: [`0003-events-table-as-single-truth.md`](./0003-events-table-as-single-truth.md) — events unification decision
- Implementation PR: #3121 (Phase 1 — split SessionEvent types)

## Status

**Accepted** (2026-04-29). Implemented in Phase 1 of the events unification stack.
