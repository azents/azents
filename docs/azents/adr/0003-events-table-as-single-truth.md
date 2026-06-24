---
title: "ADR-0003: Make the events Table the Single Source of Truth and Remove session_items_oai"
created: 2026-04-28
tags: [architecture, engine, backend]
---

# ADR-0003: Make the events Table the Single Source of Truth and Remove session_items_oai

## Context

During the OpenAI Agents SDK migration (18-PR stack, #3050-3098), a new `session_items_oai` table was introduced to persist raw SDK `TResponseInputItem` dictionaries. However, the existing `events` table was also dual-written, splitting the two stores in the following ways:

- **Duplicate storage**: the same conversation is stored in two places and two forms, parsed versus raw.
- **Permission split**: the SDK only understands its own history, while domain metadata such as compaction status, subagent boundaries, and observation masking exists only in `events`.
- **Turn definition split**: `turn_id` column in `session_items_oai` versus `TurnCompleteEvent` rows in `events`.
- **Compaction meaning split**: persistent model of deleting event rows and inserting a summary versus in-memory input replacement.
- **Data round-trip loss risk**: responsibility for synchronizing two representations is unclear.

## Decision

**Remove** the `session_items_oai` table. Redefine the `events` table as the single source of truth:

```sql
events:
  id          UUID7 PK
  session_id  FK → conversation_sessions
  type        EventType ENUM NOT NULL
  data        JSONB NOT NULL          -- UI rendering shape (snapshot at write-time)
  raw_data    JSONB NULL              -- raw OAI dict from SDK origin (round-trip)
  external_id TEXT NULL               -- dedup key
  created_at  TIMESTAMP

CREATE UNIQUE INDEX uq_events_session_external
  ON events (session_id, external_id)
  WHERE external_id IS NOT NULL;
```

**Type ENUM (15)**:

- SDK origin (`raw_data NOT NULL`): text_item, reasoning_item, function_call_item, function_call_output_item, web_search_call_item, image_generation_item, unknown_item
- NoIntern formatted (`raw_data NULL`, formatter wraps user role): user_input, system_reminder, compaction
- NoIntern meta (`raw_data NULL`, hidden from model): turn_complete, compaction_started, subagent_start, subagent_end, error

**Cross-cutting decisions**:

- **NointernSession is an EventStore adapter** — `get_items` derives from events, either passing through `raw_data` or using a formatter. `add_items` performs deduplicated INSERTs using `external_id ON CONFLICT DO NOTHING`.
- **Cross-model normalization belongs to SDK + LiteLLM** — remove the legacy `build_input_items` normalization layer such as `_is_reasoning_compatible` and `normalize_call_id`.
- **Remove the Turn data model** — delete the `turn_id` column. Derive the current turn from the number of `turn_complete` rows in events plus one.
- **dedup-by-id** — unify deduplication around SDK item ids (`raw_item.id` or `call_id`) and uuid7 hex ids assigned by the worker to NoIntern rows.
- **Migration**: discard legacy events data. This is still development-stage data, so data loss is accepted.

## Considered Options

### A. Make session_items_oai the single store, which was the direction of the existing stack

`session_items_oai` becomes the truth, while domain metadata such as compaction, subagents, and masking is stored as separate columns or non-standard keys inside `item_json`.

Reasons rejected:

- Injecting our domain metadata into the SDK's raw dict shape is awkward.
- FE `list_messages` would need to parse raw dicts, repeatedly taking responsibility for UI conversion.
- Domain events such as turn boundaries, subagent markers, and compaction markers do not match the SDK input item representation.

### B. Make events the single store, which is this decision

The `events` table is the truth, and `NointernSession` becomes a thin adapter.

Reasons accepted:

- Domain metadata is naturally represented by `events.type`.
- SDK raw round-trip data is preserved through the `raw_data` column.
- FE `list_messages` can read the `data` snapshot directly, with zero conversion cost at read time.
- The persistent compaction model from legacy `_compact()` can be reused as-is.
- `NointernSession` responsibility shrinks to a thin adapter over EventStore.

### C. New unified schema

Create a new table that stores raw, parsed, and meta data together, then derives both an SDK adapter view and a domain view.

Reasons rejected:

- Large migration cost and ongoing burden of keeping two views synchronized.
- Provides little additional value compared with option B.

### D. Keep explicit separation and make Turn first-class

Keep both stores and introduce a separate Turn metadata table. Continue dual-write.

Reasons rejected:

- Does not solve duplicate storage.
- Introducing a Turn data model was the wrong direction; later issues showed that item count does not equal turn count.

## Consequences

### Positive

- Single source of truth removes synchronization responsibility.
- Domain metadata such as compaction, subagent boundaries, and observation masking becomes first-class in events.
- `NointernSession` code is greatly reduced as an EventStore adapter.
- FE `list_messages` read cost decreases because it uses the `data` snapshot directly.
- Reuses the proven legacy compaction model.

### Negative

- The 18-PR stack is discarded, losing the review effort (Hardtack) and CI validation work already done.
- A new 11-phase stack must be written, although PORT items can be cherry-picked.
- Legacy events data is lost under migration strategy (c).

### Trust Assumptions That Need Verification

- SDK + LiteLLM cross-model normalization is at least as good as our normalization layer. Verify with integration tests in Phase 11 testenv.
- SDK `add_items` dedup-by-id works correctly, preserving ids and avoiding `FAKE_RESPONSES_ID`. Verify with unit tests.

## References

- `docs/nointern/discussion/openai-sdk-events-redesign.md` — detailed design for this decision
- `docs/nointern/discussion/18-pr-inventory.md` — inventory of the discarded stack, classified as PORT/ADAPT/DROP/REVIEW
- Discarded PRs: #3050, #3057-3098

## SDK Verification Quotes

- **Safety of add_items NO-OP, effectively dedup-INSERT**: agents/run_loop.py:1357-1361 uses in-memory `_model_input_items`; agents/run_internal/session_persistence.py:325 calls one batch.
- **ID preservation**: agents/items.py:704-715 (`input_to_new_input_list`), agents/run_internal/items.py:138-144 (`ensure_input_item_format`), 253-261 (`strip_internal_input_item_metadata`).
- **Stream emit coverage**: agents/run_internal/streaming.py:27-62 emits 11/13 RunItem types. CompactionItem does not go through streaming and only reaches add_items, which is naturally handled by dedup-INSERT.
- **Cross-model normalization**: agents/models/chatcmpl_converter.py (`items_to_messages`), agents/extensions/models/litellm_model.py:437 (`_fix_tool_message_ordering`).
