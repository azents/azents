---
title: "LLM Event Storage/Reconstruction Redesign Historical Requirements Reconstruction"
created: 2026-03-04
implemented: 2026-03-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: llm-260304
historical_reconstruction: true
migration_source: "docs/azents/design/llm-event-storage-redesign.md"
---

# LLM Event Storage/Reconstruction Redesign Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `llm-260304`
- Source: `docs/azents/design/llm-260304-llm-event-redesign.md`
- Historical source date basis: `2026-03-04`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

1. **Information loss**: original structure is lost during decomposition
   - Example: `OutputMessage` content and `FunctionCall`s from same turn are separated into different SessionEvent types, and reconstruction creates structure different from original.
2. **Reconstruction bug**: provider constraints are violated when separated fragments are combined again
   - Real case: empty assistant message inserted after reasoning item violates GPT constraint "reasoning must be followed by its output" (`litellm.BadRequestError`).
3. **Maintenance burden**: `_parse_response_output` (decomposition) ↔ `_build_input_items` (reconstruction) must be exactly symmetric, but logic on both sides is written independently and can diverge.
4. **Inefficient token cache**: reconstruction into structure different from original lowers provider prompt cache hit rate.

## Primary Actor

**File:** `nointern/runtime/llm.py`

Core change:

```python
for event in events:
    # use original if raw_output exists and same model
    if hasattr(event, 'raw_output') and event.raw_output and source_model == model:
        items.append(event.raw_output)
        continue
    # otherwise: existing normalized logic
    match event:
        case UserInputEvent(...): ...
        case AssistantTextEvent(...): ...
        ...
```

**Notes**:
- `UserInputEvent`, `ToolResultEvent` never have `raw_output`, so always use existing logic.
- trailing reasoning removal logic is maintained even in raw mode (defense against failed response).
- Existing workaround (`if content:` empty string check) can be removed.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- **Lossless round-trip**: no information loss in LLM output → DB → LLM input process
- **Client compatibility**: keep existing REST API / WebSocket streaming contract
- **Cross-model support**: fallback to normalized columns on model switch
- **Special cases such as images**: binary data keeps existing extract & replace pattern

---

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
