---
title: "OpenAI SDK Migration — Events Unification Redesign"
tags: [engine, architecture, historical-reconstruction]
created: 2026-04-28
updated: 2026-04-28
implemented: 2026-04-28
document_role: primary
document_type: design
snapshot_id: events-260428
migration_source: "docs/azents/design/openai-sdk-events-redesign.md"
historical_reconstruction: true
---

# OpenAI SDK Migration — Events Unification Redesign

## Background

Existing 18-PR stack structured OpenAI Agents SDK migration as follows:
- new `session_items_oai` table → persist raw dict of SDK `TResponseInputItem`
- existing `events` table → persist existing SessionEvent (parsed), exposed to FE
- dual-write to both stores (transition state)

Problems:
- Same conversation stored in two places in two forms (duplicate storage)
- Domain metadata such as compaction / observation masking / subagent boundary exists only in events and SDK does not know it
- Turn definition split across both sides (turn_id column vs TurnCompleteEvent row)
- Compaction has two meanings (persistent row deletion + summary INSERT vs in-memory input replacement)

Direction: **unify on events table**. Discard session_items_oai. NointernSession is thin adapter on top of EventStore.

## Decisions

### A. Schema

**events table (6 columns)**:

```sql
events:
  id          UUID7 PK
  session_id  FK → conversation_sessions
  type        EventType ENUM NOT NULL
  data        JSONB NOT NULL          -- UI rendering form (snapshot)
  raw_data    JSONB NULL              -- raw OAI dict from SDK origin
  external_id TEXT NULL               -- dedup key (SDK item id or worker-assigned id)
  created_at  TIMESTAMP

CREATE UNIQUE INDEX uq_events_session_external
  ON events (session_id, external_id)
  WHERE external_id IS NOT NULL;
```

**Discarded columns** (from legacy 13 columns):
- role / content / tool_calls / tool_call_id / metadata / attachments / reasoning / model / raw_output / usage — all absorbed into `data` or `raw_data`
- model information remains only inside turn_complete.data.model (for audit)
- usage is turn_complete.data.usage. Separate aggregate table may be introduced later.

### B. Type ENUM (15 types)

```python
class EventType(str, Enum):
    # SDK origin — Passthrough (raw_data NOT NULL)
    TEXT_ITEM = "text_item"
    REASONING_ITEM = "reasoning_item"
    FUNCTION_CALL_ITEM = "function_call_item"
    FUNCTION_CALL_OUTPUT_ITEM = "function_call_output_item"
    WEB_SEARCH_CALL_ITEM = "web_search_call_item"
    IMAGE_GENERATION_ITEM = "image_generation_item"
    UNKNOWN_ITEM = "unknown_item"

    # NoIntern-formatted (raw_data NULL, formatter wraps as user role)
    USER_INPUT = "user_input"
    SYSTEM_REMINDER = "system_reminder"
    COMPACTION = "compaction"

    # NoIntern-meta (raw_data NULL, no formatter, model-hidden)
    TURN_COMPLETE = "turn_complete"
    COMPACTION_STARTED = "compaction_started"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    ERROR = "error"
```

Represented as **Postgres native ENUM** (more explicit catalog value than TEXT + CHECK).

**background_event is not separate type** — origin is expressed by system_reminder.data.source (e.g. `"background_tool_result"`, `"compaction_warning"`).

### C. Relationship between data and raw_data

- **Snapshot at write-time**: For SDK origin, parser converts raw_data → data once at emit time and persists both.
- **When parser evolves**: default is frozen snapshot (data of old rows keeps old shape). If consistency is needed, run backfill migration.
- **Zero parse on read**: UI always reads only data. No deep parsing of raw_data.

### D. Invariant (DB CHECK constraint)

```sql
CHECK (
  (type IN ('text_item', 'reasoning_item', 'function_call_item',
            'function_call_output_item', 'web_search_call_item',
            'image_generation_item', 'unknown_item')
   AND raw_data IS NOT NULL)
  OR
  (type IN ('user_input', 'system_reminder', 'compaction',
            'turn_complete', 'compaction_started',
            'subagent_start', 'subagent_end', 'error')
   AND raw_data IS NULL)
)
```

DB enforces integrity. Even if application bug breaks invariant, INSERT is rejected.

### E. Per-type data shape

| type | data shape | raw_data |
|---|---|---|
| `text_item` | `{text, attachments}` | raw OAI message dict |
| `reasoning_item` | `{reasoning_text, summary}` | raw reasoning dict |
| `function_call_item` | `{name, arguments, call_id}` | raw function_call dict |
| `function_call_output_item` | `{call_id, output, attachments}` | raw function_call_output dict |
| `web_search_call_item` | `{query, results}` | raw web_search_call dict |
| `image_generation_item` | `{attachments}` | raw image_generation_call dict |
| `unknown_item` | `{}` or summary | raw dict |
| `user_input` | `{content, headers, metadata, attachments, images}` | NULL |
| `system_reminder` | `{text, source}` | NULL |
| `compaction` | `{summary_text}` | NULL |
| `turn_complete` | `{model, usage}` | NULL |
| `compaction_started` | `{}` | NULL |
| `subagent_start` | `{subagent_id, subagent_name, subagent_session_id}` | NULL |
| `subagent_end` | `{subagent_id, subagent_session_id, result}` | NULL |
| `error` | `{content}` | NULL |

### F. Separate Function call ↔ output

Legacy: 1 row (call+output integrated in FunctionCallItem)
New: 2 rows (SDK's function_call and function_call_output respectively)

- **Atomicity**: legacy output=None == absence of output row in new design. Same meaning. If crash occurs during tool execution, state with only call row is naturally represented.
- **UI correlation**: application-level pairing — `MessageRepository.list_messages` receives events and groups by call_id. No DB view / client-side join.
- **Pagination boundary**: simple row-level limit. UI prepares for unmatched cases (lone call or lone output). Natural merge when "load more" clicked.
- **emit order**: depends on uuid7 timestamp sort. redis session lock blocks same-session concurrent INSERT, so clock skew risk ignored.

### G. Parser / Formatter Separation

```
engine/events/parsers.py     — raw → data conversion for SDK origin types (write direction)
engine/events/formatters.py  — data → user role conversion for NoIntern types (read direction)
```

SDK origin and NoIntern origin are disjoint type sets, so they are not pairs:

| Group | parser (write) | formatter (read) |
|---|---|---|
| SDK origin (text_item, etc.) | ✅ | ❌ (raw_data passthrough) |
| NoIntern formatted (user_input, etc.) | ❌ | ✅ |
| NoIntern meta (turn_complete, etc.) | ❌ | ❌ (skip) |

### H. Emit pipeline

```
SDK stream event:
  RawResponsesStreamEvent (token delta)
    → ephemeral UI emit only, no INSERT
  RunItemStreamEvent (item completion)
    → durable emit → INSERT (raw_data + parsed data + external_id)

Worker:
  receive user input → INSERT user_input row (worker assigns external_id)
                     → Runner.run_streamed(input=..., session=NointernSession)

NoIntern emit (system_reminder, subagent_*, error, etc.):
  → durable emit → INSERT (raw_data NULL, data directly constructed)

SDK add_items (turn end batch):
  → try INSERT for all received items (ON CONFLICT DO NOTHING with external_id)
  → items already INSERTed by stream are skipped
  → items that do not pass through stream, such as CompactionItem, are newly INSERTed
  → caller input conflicts with external_id assigned by worker → skipped
```

### I. NointernSession (EventStore adapter)

```python
class NointernSession(SessionABC):
    def __init__(self, session_id, event_store, model_id):
        self._sid = session_id
        self._store = event_store
        self._model = model_id

    async def get_items(self, limit=None) -> list[TResponseInputItem]:
        events = await self._store.list(self._sid)
        items = []
        for event in events:
            if event.type in NON_MODEL_VISIBLE_TYPES:
                continue
            if event.raw_data is not None:
                items.append(event.raw_data)              # SDK passthrough
            else:
                fmt = FORMATTERS[event.type]
                items.extend(fmt.to_input_items(event))   # NoIntern → user role
        return items[-limit:] if limit else items

    async def add_items(self, items):
        # Try INSERT for all incoming items. DB handles dedup.
        for item in items:
            ext_id = item.get("id") or item.get("call_id")
            if ext_id == FAKE_RESPONSES_ID:
                continue
            type_, data = classify_and_parse(item)
            await self._store.upsert_event(
                session_id=self._sid,
                type=type_,
                data=data,
                raw_data=item,
                external_id=ext_id,
            )

    async def pop_item(self) -> None: return None  # NO-OP
    async def clear_session(self) -> None: pass     # NO-OP
```

**SDK contract safety** (SDK code verified):
- SDK does not call get_items again in same run after add_items (uses in-memory `_model_input_items`).
- SDK internal logic does not depend on return value / side-effect of add_items.
- pop_item / clear_session are not called in our use path (rewind feature unused).
- Therefore, SDK behavior is unaffected even when add_items operates as dedup-INSERT-or-skip.

### J-pre. Image storage and lifecycle

**Original preservation**: originals of all images (user upload, generated) are stored in **sandbox filesystem**. URI in events.data.attachments points to that path. Permanently preserved, no DB burden.

**LLM input form**: images included in LLM input each time are resized base64 at 1520-1568 px (data URL or image_generation_call.result). Persisted in this form inside events.raw_data.

**Natural disappearance mechanism** (solves token burden of long sessions):
- **ImageLifecycleFilter** (gradual resize): progressively reduces 1568 → 1024 → 300 px as turns progress. Directly UPDATEs DB raw_data.
- **ObservationMaskingFilter** (tool mask): masks content of function_call_output outside protection interval with `[Output hidden]`. Images inside tool result are naturally hidden too.
- Result: very old images become smaller in model input, then are replaced by [image] text or hidden by tool mask. Originals remain in sandbox.

**Round-trip**: image_generation_call.result or input_image.image_url in events.raw_data is already 1520 px base64 — SDK sends it to model as-is. No compatibility risk such as URI conversion.

### J. Cross-model normalization

**SDK + LiteLLM are responsible** (verified):
- SDK `Converter.items_to_messages()` (chatcmpl_converter.py) converts OpenAI Responses dict → ChatCompletion form.
- LitellmModel `_fix_tool_message_ordering()` handles Anthropic/Claude/Gemini compatibility.
- LiteLLM does final conversion into provider-specific raw form.

**Remove legacy build_input_items normalization layer**:
- `_is_reasoning_compatible()` (model-specific reasoning skip) → SDK automatically converts to reasoning_content field.
- `normalize_call_id()` (SHA-256) → LiteLLM responsibility.
- raw round-trip compatibility gating (`event.model == current_model`) → unnecessary. Always passthrough raw_data.

**Remaining verification needed**:
- Whether Reasoning item is silently dropped in other providers such as Anthropic/Bedrock (integration test).
- Whether LiteLLM automatically truncates call_id length constraints.

### K. Dedup-by-id

**All SDK items have id** (verified):
- message: id Required (assistant provided by OpenAI, user provided by caller)
- reasoning: id Required
- function_call: id Optional + call_id Required
- function_call_output: id Optional + call_id Required (call_id fallback)
- web_search_call / image_generation_call: id Required
- CompactionItem: id Required

**SDK preserves caller input id** (`input_to_new_input_list` → `ensure_input_item_format` → `strip_internal_input_item_metadata` does not touch id).

**id at stream time == id at add_items time**:
- run_item_to_input_item includes raw_item.id in dict as-is.
- normalize stage also preserves id.

**external_id decision rule**:
1. if `item.get("id")` exists and != FAKE_RESPONSES_ID, use it
2. otherwise `item.get("call_id")` (fallback for function_call_output)
3. NoIntern-created row is assigned by worker (e.g. `"nointern_user_<uuid7>"`)
4. NoIntern meta type (turn_complete, etc.) is NULL

### L. Partial event handling

**partial is not persisted** — token delta is for real-time UI display, not persistent value.

| Stream event | Persisted? | UI? |
|---|---|---|
| RawResponsesStreamEvent (token delta) | ❌ | ✅ ephemeral emit |
| RunItemStreamEvent (item completion) | ✅ INSERT | ✅ |

**Crash-time meaning**:
- stream-completed items → persisted in events (survive)
- in-progress item → lost (natural because SDK did not emit completion signal)
- no equivalent partial preservation to legacy output=None

### M. Migration Strategy

**discard legacy events data**: apply only new schema. 0 row conversion logic. Accept loss of existing conversation history (development/internal usage stage).

## Additional Decisions (M1-M5, A-F)

### M1. Turn complete row emission timing → response.completed event

SDK stream `response.completed` (RawResponsesStreamEvent) → emit pipeline → INSERT turn_complete row.
- Natural position at end after all RunItemStreamEvent INSERTs of same turn (uuid7 sort)
- usage information is in event payload, so separate state tracking unnecessary
- add_items timing is naturally redundant due to dedup

### M2. Fate of ImageLifecycleFilter → operates on events (β)

Keep ImageLifecycleFilter, operate on events:
- On each call, one pass over events to simultaneously (a) find image rows + (b) calculate age by turn_complete count + (c) handle boundary
- age = current_turn - row's turn_index (single pass count)
- On transition turns (age 1, 3, 10), downsize image content in raw_data + DB UPDATE
- No separate turn_index column / separate data model needed
- Natural disappearance: gradual resize + ObservationMaskingFilter (tool mask) work together

### M3. 18-PR Stack handling → close existing stack + start new stack (A)

- Close all existing 18 PRs (#3050, #3057-3098), and add close reason + link to this redesign doc to each PR.
- Keep branches alive (for cherry-pick / inventory PORT item reference).
- Rebuild new stack from main base into 11 phases.

### M4. CompactionFilter → persistent model (borrow legacy `_compact()`) + separate ObservationMaskingFilter

- CompactionFilter: legacy `_compact()` persistent model. DELETE rows before boundary + INSERT compaction event row (one transaction). Depends only on redis session lock, no DB advisory lock.
- ObservationMaskingFilter (separate filter): threshold-triggered, replaces content of function_call_output outside protection interval with `[Output hidden]` in memory. Not persisted.
- Filter chain order: injection → image_lifecycle → observation_masking → compaction. Each measures own threshold (cheap).

### M5. Background event → Worker-managed system_reminder INSERT

Worker tracks BackgroundHandle of background tool. When completion detected, directly INSERT type=system_reminder, data.source="background_tool_result" row into events. At next turn start, NointernSession.get_items naturally includes it.

### A. Ephemeral emit (UI delivery) data structure → keep Legacy ContentDelta / ReasoningDelta dataclass

Keep Legacy UI client compatibility. ephemeral is not persisted, so there is little value forcing 1:1 match with events type. Simple dataclass carrying only token text.

### B. external_id prefix rule → uuid7 hex (no prefix)

external_id of NoIntern-origin row is only uuid7 hex. type column sufficiently indicates origin. Naturally distinguishable from SDK OpenAI id (msg_*, fc_*).

### C. Caller input format → list[TResponseInputItem] with worker-assigned id

Worker assigns external_id when inserting user_input. The same id is passed as id field of Runner.run_streamed input dict. SDK preserves id → same id arrives at add_items → ON CONFLICT skip → dedup naturally works.

### D. Phase split → 11 phases

Critical path 8 + auxiliary 3:

1. Design documents (redesign + inventory + ADR)
2. events schema (alembic + ENUM + RDBEvent + CHECK)
3. events package (parsers + formatters + emitter)
4. NointernSession (EventStore adapter)
5. LLM Model + DynamicAgent + tool_converter (PORT)
6. Filters (4 types + CompactionStrategy)
7. EngineAdapter + Worker integration
8. MessageRepository + list_messages + AgentEngine replacement
9. Subagent + Sandbox Adapter + SkillScanner (PORT)
10. Manifest + Guardrails + RunState + load_skill + DockerSandbox (PORT)
11. Remove EFS + dead code + testenv + spec + cleanup

### E. MVP scope → not applicable, full migration

This work is **full migration**, not MVP. Once all 11 phases are merged, it provides quality and feature-set parity with existing code level. No follow-up.

### F. Test strategy → unit + integration

- **Unit**: parser/formatter tests per type, NointernSession dedup tests, Filter chain tests (included in Phase 3, 4, 6). Existing session_test/filters_test/engine_adapter_test are rewritten for new schema.
- **Integration**: SDK + LiteLLM cross-model scenarios in testenv or azents-e2e (reasoning + function_call + image multipart round-trip for Bedrock Claude / Anthropic / OpenAI). Together with Phase 11 testenv item.

## Next Steps

1. Merge this redesign doc + inventory + ADR 0003 (events unification decision) into main as first docs PR.
2. Close existing 18 PRs (#3050, #3057-3098) + link this docs + comment mapping for corresponding inventory items.
3. Proceed sequentially from new stack Phase 2 (events schema → events package → NointernSession → ...).
4. Migration complete when all through Phase 11 are merged.

## Verification Evidence Quotes

SDK behavior assumptions in this document were verified with following code:

- **add_items safety**: agents/run_loop.py:1357-1361 (in-memory `_model_input_items` use), agents/run_internal/session_persistence.py:325 (one batch call)
- **id preservation**: agents/items.py:704-715 (input_to_new_input_list), agents/run_internal/items.py:138-144 (ensure_input_item_format), 253-261 (strip_internal_input_item_metadata)
- **stream emit coverage**: agents/run_internal/streaming.py:27-62 (stream_step_items_to_queue) — emits 11/13 RunItem types
- **CompactionItem missing from stream**: agents/items.py:462-470, agents/turn_resolution.py:1587-1594 (no stream emit, only add_items)
- **Cross-model normalization**: agents/models/chatcmpl_converter.py (items_to_messages), agents/extensions/models/litellm_model.py:437 (_fix_tool_message_ordering)
