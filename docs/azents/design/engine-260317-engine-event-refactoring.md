---
title: "Engine Event Flow Refactoring"
tags: [engine, historical-reconstruction]
created: 2026-03-17
updated: 2026-04-20
implemented: 2026-04-20
document_role: primary
document_type: design
snapshot_id: engine-260317
migration_source: "docs/azents/design/engine-event-refactoring.md"
historical_reconstruction: true
---

# Engine Event Flow Refactoring

## 1. Overview

### Goals

Simplify and make consistent the engine event emit and store flow.

### Core Changes

- Redefine LLM client as a **transparent pass-through layer**
- Remove `Durable*` prefix and align with LLM API naming
- Integrate call + output into `FunctionCallItem` (1 row)
- Simplify emit into three modes: `durable` / `update` / `ephemeral` (remove buffer/flush/internal)
- Consolidate duplicate events (delete `TextEnd`, `ReasoningEnd`, `ToolCallStart`)
- Switch WS protocol to per-event unique type
- Pass delta unchanged to adapter and move accumulation responsibility to adapter
- Manage in-memory history (remove DB reload every turn)

### Removed items

| Item | Reason |
|------|------|
| `repair_orphan_tool_calls()` | orphan impossible after call+output integration |
| `interleave_tool_calls()` | reorder unnecessary because call+output is 1 row |
| `save_error_message()` | use regular emit path with `Error` event |
| `image_cache` / `_inject_cached_images()` | replaced by `FunctionCallOutput.images` in-memory |
| `TextPartial` / `ReasoningPartial` | engine passes delta unchanged |
| `TextEnd` / `ReasoningEnd` / `ToolCallStart` | integrated into durable events |
| `internal()` emit | deleted; replaced with `durable()` |
| buffer/flush logic | replaced with immediate DB write |

---

## 2. LLM Client

### Design Principles

Pass LLM API response **transparently**.
- **Does**: convert LiteLLM types → our types (decoupling)
- **Does not**: process, omit, or synthesize information

### Stream Events

#### Delta

| Event | API source | Notes |
|--------|---------|------|
| `ContentDelta` | `OutputTextDeltaEvent` | includes `content_index` |
| `FunctionCallDelta` | `FunctionCallArgumentsDeltaEvent` | remove `OutputItemAddedEvent` synthesis |
| `ReasoningDelta` | `ReasoningSummaryTextDeltaEvent` | |

delta is real delta (incremental). Do not convert to accumulated partial.

#### Completed Items

Yield in output order at `ResponseCompletedEvent` time.

| Event | API source | Notes |
|--------|---------|------|
| `TextItem` | `ResponseOutputMessage` | pass parts array as-is |
| `FunctionCallItem` | `ResponseFunctionToolCall` | local execution target |
| `WebSearchCallItem` | `ResponseFunctionWebSearch` | server-side. includes result |
| `ImageGenerationCallItem` | `ImageGenerationCall` | server-side. includes base64 result |
| `ReasoningItem` | `ResponseReasoningItem` | |
| `UnknownItem` | unparsed type | keep raw, preserve same-model round-trip |
| `ResponseCompleted` | `ResponseCompletedEvent` | pass usage. final stream item |

### Output item classification

```
output items
├── text/reasoning
│   ├── ResponseOutputMessage (message) → TextItem
│   └── ResponseReasoningItem (reasoning) → ReasoningItem
├── local tool (executed by us)
│   └── ResponseFunctionToolCall (function_call) → FunctionCallItem
│       → after execution, add FunctionCallOutput to next-turn input
├── server-side tool (executed by LLM, includes result)
│   ├── ResponseFunctionWebSearch (web_search_call) → WebSearchCallItem
│   └── ImageGenerationCall (image_generation_call) → ImageGenerationCallItem
│       → raw can be inserted as-is into next-turn input
└── unparsed
    └── UnknownItem → keep raw
```

Server-side tools share traits (include result, no output needed), but engine post-processing differs:
- `web_search_call` — no post-processing. preserve raw only.
- `image_generation_call` — base64 decoding, session storage save, attachment creation.

→ LLM client passes each type as-is, and engine handles each type.

### TextItem multi-part

`ResponseOutputMessage.content` is a list of `ResponseOutputText | ResponseOutputRefusal`.

- Generally one text part
- Cases where multiple may arrive: web_search annotation, refusal + text combination
- Preserve parts array as-is. Do not join.
- delta `content_index` corresponds to parts array index

### Next-turn input format

#### Input item classification

- **User message**: `Message` (role: user/system/developer)
- **Previous-turn LLM response**: reinsert output items as-is
- **Added by us**: `FunctionCallOutput` (matched by call_id)

#### Expected order for multi function call

```
[previous conversation...]
ResponseReasoningItem          ← LLM response as-is
ResponseOutputMessage          ← LLM response as-is
ResponseFunctionToolCall#1     ← LLM response as-is
FunctionCallOutput#1           ← added by us
ResponseFunctionToolCall#2     ← LLM response as-is
FunctionCallOutput#2           ← added by us
ResponseFunctionWebSearch      ← LLM response as-is (no output needed)
ImageGenerationCall            ← LLM response as-is (no output needed)
```

#### Core principles

- Reinsert LLM response output items **as-is**
- Insert our `function_call_output` only after `function_call`
- Server-side tool remains as-is (no output addition needed)

---

## 3. Engine

### Naming

Remove `Durable*` prefix. Events from LLM have same names as LLM client.

| Current | New | Reason |
|------|------|------|
| `DurableAssistantText` | `TextItem` | same as LLM `TextItem` |
| `DurableReasoning` | `ReasoningItem` | same as LLM `ReasoningItem` |
| `DurableToolCall` | `FunctionCallItem` | same as LLM `FunctionCallItem` |
| `DurableToolResult` | (deleted) | integrated into `FunctionCallItem.output` |
| `DurableSubagentStart` | `SubagentStart` | |
| `DurableSubagentEnd` | `SubagentEnd` | |

#### Unify data-structure Function prefix

| Current | New |
|------|------|
| `ToolCall(id, name, arguments)` | `FunctionToolCall(id, name, arguments)` |
| `ToolSpec(name, description, input_schema)` | `FunctionToolSpec(name, description, input_schema)` |
| `ToolResult(content, attachments, images)` | `FunctionToolResult(content, attachments, images)` |
| `ToolError` | `FunctionToolError` |
| `Tool(spec, handler)` | `FunctionTool(spec, handler)` |

### Emit system

Only three exist:

| emit | Behavior | Use |
|------|------|------|
| `durable()` | immediate DB INSERT + adapter delivery | store new event |
| `update()` | immediate DB UPDATE + adapter delivery | modify existing event (FunctionCallItem output, etc.) |
| `ephemeral()` | adapter delivery only | delta, state notification, etc. |

- delete `internal()`
- delete buffer/flush — one turn has only about 5~6 durable events, so batch INSERT unnecessary
- `UnknownItem` also uses `durable()`. Adapter ignores it.
- `TurnCompleteEvent` also uses `durable()`. Deliver turn boundary to adapter.

### Event consolidation

Consolidate what used to be separate DB events and WS events:

| Deleted | Integrated target | Method |
|------|----------|------|
| `TextEnd` | `TextItem` | `TextItem` durable emit is final text |
| `ReasoningEnd` | `ReasoningItem` | `ReasoningItem` durable emit confirms reasoning |
| `ToolCallStart` | `FunctionCallItem` | `output=None` → running, output exists → complete |
| `TextPartial` | `ContentDelta` | engine passes delta as-is |
| `ReasoningPartial` | `ReasoningDelta` | engine passes delta as-is |
| `ErrorEnd` | `Error` | rename + regular emit instead of `save_error_message()` |

### FunctionCallItem — call + output integration

```python
@dataclasses.dataclass(frozen=True)
class FunctionCallOutput:
    content: str
    attachments: list[Attachment] = []

@dataclasses.dataclass(frozen=True)
class FunctionCallItem:
    id: str
    tool_call: FunctionToolCall
    raw_output: dict | None = None
    source_model: str | None = None
    output: FunctionCallOutput | None = None  # None means not executed
```

lifecycle:
1. LLM response → `yield durable(FunctionCallItem(output=None))` → DB INSERT, deliver "running" to adapter
2. tool execution complete → `yield update(item.replace(output=...))` → DB UPDATE, deliver result to adapter

Maintain immutability with frozen dataclass + `dataclasses.replace()`.

→ Delete `interleave_tool_calls()` — call+output is 1 row, so order is always correct
→ Delete `repair_orphan_tool_calls()` — output null creates synthetic output in `build_input_items()`

### FunctionCallOutput.images — in-memory only

```python
@dataclasses.dataclass(frozen=True)
class FunctionCallOutput:
    content: str
    attachments: list[Attachment] = []  # stored in DB
    images: list[ImageSource] = []     # not stored in DB, only in-memory within run
```

- ImageBlob returned by tool is kept in `images`
- Remains in in-memory history until next turn
- Disappears when run ends (already analyzed)
- Delete `image_cache` / `_inject_cached_images()`

### ImageGenerationCallItem → GeneratedImage

base64 source must not be stored in DB (size). Engine converts it:

```python
@dataclasses.dataclass(frozen=True)
class GeneratedImage:
    id: str
    attachments: list[Attachment]  # URI + thumbnail
```

- `durable()`: DB save + adapter delivery (file upload)
- In `build_input_items()`, render attachment as text and include as assistant message
- Do not store raw

### Error event

```python
@dataclasses.dataclass(frozen=True)
class Error:
    id: str
    content: str
```

Delete `save_error_message()`. Errors also use regular emit path:
```python
yield durable(Error(content=error_msg))
```

### History management: keep in-memory

- Load once from DB at run start
- Append new event to in-memory history + immediate DB write
- DB reload only after compaction
- Also append `poll_messages()` result to in-memory

### Normalize server tool on model change

If model changes in the middle of a session, previous model's server tool raw is not recognizable by new model.

| Event | Same model | Different model |
|--------|----------|----------|
| `FunctionCallItem` | raw round-trip | normalized `function_call` + `function_call_output` |
| `WebSearchCallItem` | raw round-trip | summarize as assistant message ("Performed a web search.") |
| `GeneratedImage` | render attachment text | same (no raw, model-independent) |
| `UnknownItem` | raw round-trip | skip |

Do not disguise server tool as `function_call`.

### New turn flow

```
1. Request input → append user_messages to in-memory history + DB write
   └ yield ephemeral(RunStarted)

while True:
  2. Prepare history
     ├ use in-memory history (no DB reload)
     ├ filter subagent events
     └ proactive compaction (when token estimate > threshold)
       ├ yield ephemeral(CompactionStarted / CompactionComplete)
       └ after compaction, reload DB → update in-memory

  3. History → LLM input conversion (build_input_items)
     └ build CompletionRequest

  4. Call LLM streaming
     │
     │ Delta events:
     │  ContentDelta      → yield ephemeral(ContentDelta)       ← pass as-is
     │  ReasoningDelta    → yield ephemeral(ReasoningDelta)     ← pass as-is
     │  FunctionCallDelta → yield ephemeral(FunctionCallDelta)  ← pass as-is
     │
     │ Completed items:
     │  TextItem               → yield durable(TextItem)
     │  ReasoningItem          → yield durable(ReasoningItem)
     │  FunctionCallItem       → collect in function_calls
     │                           yield durable(FunctionCallItem(output=None))
     │  WebSearchCallItem      → yield durable(WebSearchCallItem)
     │  ImageGenerationCallItem→ base64 decode → store
     │                           yield durable(GeneratedImage(attachments))
     │  UnknownItem            → yield durable(UnknownItem)
     │  ResponseCompleted      → capture usage
     │
     │ Exceptions:
     │  ContextWindowExceeded → compaction → continue
     │  OpenAIAPIError → yield durable(Error) → return
     │
     └ streaming ends

  5. function_calls empty?
     │  (includes case with server-side tools only)
     ├ Yes → yield durable(TurnComplete)
     │       ├ server-side durable exists? → continue (next turn)
     │       └ none → yield ephemeral(RunComplete) → return
     │
     └ No → execute local tools
       ├ yield durable(TurnComplete)
       │
       └ for each function_call:
         ├ stop check → if cancelled, yield ephemeral(RunStopped) → return
         │              (remaining FunctionCallItem keeps output=None
         │               → next run build_input_items creates synthetic output)
         ├ execute tool.handler()
         └ yield update(function_call_item.replace(output=...))

  6. poll_messages() → inject new user message if any
     └ continue
```

`function_calls` collects only `FunctionCallItem` (local tool). Server-side tools (WebSearchCallItem, ImageGenerationCallItem) are not collected because they are already stored with durable emit and there is nothing to execute.

Simplify previous dual tracking `served_ids` + `tool_calls` into single `function_calls` list.

### Full Ephemeral Event List

| Event | Use |
|--------|------|
| `ContentDelta` | text streaming (as-is from LLM) |
| `ReasoningDelta` | reasoning streaming (as-is from LLM) |
| `FunctionCallDelta` | function call arguments streaming (as-is from LLM) |
| `RunStarted` | execution start |
| `RunComplete` | execution complete |
| `RunStopped` | execution stopped |
| `CompactionStarted` / `CompactionComplete` | compaction state |
| `SessionTitleUpdated` | title update |
| `AccountLinkNudgeEvent` | account-linking nudge |

### Full Durable Event List

| Event | Use |
|--------|------|
| `TextItem` | text response (preserve parts array) |
| `ReasoningItem` | reasoning |
| `FunctionCallItem` | function call + output (running when output=None) |
| `WebSearchCallItem` | web search (preserve raw) |
| `GeneratedImage` | image generation (store only attachment) |
| `UnknownItem` | unparsed output (preserve raw) |
| `SubagentStart` / `SubagentEnd` | subagent lifecycle |
| `TurnComplete` | turn boundary |
| `Error` | error message |

---

## 4. Adapter / WS Protocol

### WS protocol

Discard previous integrated format `type: "message"` + `status: "partial"/"complete"`.
Switch to per-event unique type. Frontend migrates at the same time.

#### Message events

```json
// text streaming delta
{"type": "content_delta", "id": "msg_1", "content_index": 0, "delta": "text chunk"}

// reasoning streaming delta
{"type": "reasoning_delta", "id": "msg_1", "delta": "reasoning chunk"}

// function call arguments streaming delta
{"type": "function_call_delta", "id": "fc_1", "delta": "arguments chunk"}

// finalized text
{"type": "text_item", "id": "msg_1", "parts": [
  {"type": "output_text", "text": "full text"}
], "attachments": []}

// finalized reasoning
{"type": "reasoning_item", "id": "msg_1", "reasoning_summary": "full reasoning"}

// function call (running)
{"type": "function_call_item", "id": "fc_1",
 "tool_call": {"id": "fc_1", "name": "search", "arguments": "{...}"},
 "output": null}

// function call (complete)
{"type": "function_call_item", "id": "fc_1",
 "tool_call": {"id": "fc_1", "name": "search", "arguments": "{...}"},
 "output": {"content": "result", "attachments": []}}

// image generation complete
{"type": "generated_image", "id": "img_1", "attachments": [...]}

// error
{"type": "error", "id": "err_1", "message": "error message"}
```

#### Control events (keep existing)

```
run_started, run_complete, run_stopped,
compaction_started, compaction_complete,
sandbox_initializing, sandbox_ready, sandbox_error,
subagent_stream_start, subagent_stream_end,
session_created, session_title_updated,
authorization_request, account_link_nudge
```

#### Core changes

- Remove `status: "partial"/"complete"` → delta events stream and item events finalize
- `function_call_item` is resent with same id → frontend upserts by id
- No need for "all partial→complete" logic on `run_complete` (keep cleanup only for abnormal termination)

### Frontend delta handling

Delta is passed as raw delta. Frontend accumulates by `content_index`:

```
ContentDelta(content_index=0, delta="a") → parts[0] += "a"   // parts[0] = "a"
ContentDelta(content_index=0, delta="b") → parts[0] += "b"   // parts[0] = "ab"
ContentDelta(content_index=1, delta="c") → parts[1] += "c"   // parts[1] = "c"
TextItem(parts=[...])                     → replace with final confirmation
```

Each part is rendered as a separate bubble.

### Slack adapter

Separate `chat_stream` instance per `content_index`:

```python
self._streamers: dict[int, ChatStream] = {}
```

```
ContentDelta(content_index=0, delta="a") → create streamers[0], append("a")
ContentDelta(content_index=1, delta="c") → create streamers[1], append("c")
TextItem(parts=[...])                     → each streamer.stop(metadata=...)
```

- Since delta is real delta, delete previous reverse calculation `text[len(self._last_text):]`
- Delete duplicate handling of `TextEnd` and `DurableAssistantText` → handle only `TextItem`
- `FunctionCallItem(output=None)` → `set_status("Running {name}…")`
- `FunctionCallItem(output=...)` (update) → upload attachment files

### Discord adapter

- Ignore delta (no streaming)
- `TextItem` → send separate message per part
- `FunctionCallItem(output=None)` → show "running"
- `FunctionCallItem(output=...)` → show result + upload files

### Adapter FunctionCallItem handling

Adapter does not need to distinguish new/update. When `handle_event()` receives `FunctionCallItem`:
- `output is None` → show running state
- `output is not None` → show complete state + upload files

Since id is the same, adapter can upsert.

---

## 5. Data Migration

Use Alembic migration to convert existing data to new structure **best-effort**. Prefer simplicity over perfect restoration.

### Main conversions

#### 1. `DurableToolCall` → `FunctionCallItem` (split 1 row → N rows)

- Split `DurableToolCall.tool_calls` list into individual `FunctionCallItem` rows
- If matching `DurableToolResult` exists, match by `tool_call_id` and merge as output
- **tool_call without result → `output=None`** (`build_input_items` creates synthetic output)
- **orphan result without tool_call → skip** (delete)

#### 2. server-side tool (`DurableToolCall` with server raw + `DurableToolResult`) → delete

- Delete all server-side tool calls/results
- They disappear from history, but this is the same handling as model switch (safe to ignore)

#### 3. `DurableAssistantText(content="", attachments=[...])` → `GeneratedImage`

- Convert when content is empty string and attachments exist

### Notes

- When splitting 1 row → N rows in conversion 1, `seq` (order) must be recalculated
- `observation_mask` (compaction) path changes from `DurableToolResult.content` to `FunctionCallItem.output.content`

---

## 6. Implementation Plan

Each Phase is submitted as an independent PR (stacked). Phase dependency: `1 → 2 → 3 → 4 → 5 → 6`.

Deployment units: Phases 1~4 can each deploy independently (Phase 4 is expand-then-contract). Phase 5 requires simultaneous backend+frontend deploy. Phase 6 can run any time after Phase 4.

---

### Phase 1: FunctionTool* rename

**Goal**: Rename `Tool*` → `FunctionTool*` structures. Pure mechanical rename.

**`engine/types.py`**:
- `ToolCall` → `FunctionToolCall`
- `ToolSpec` → `FunctionToolSpec`
- `ToolResult` → `FunctionToolResult`
- `ToolError` → `FunctionToolError`
- `Tool` → `FunctionTool`
- `ToolHandler` → `FunctionToolHandler`
- `BuiltinToolSpec` — keep (server-side tool, not Function)

**Import update targets** (replace_all):

| File | Symbols changed |
|------|-------------|
| `engine/engine.py` | ToolCall, ToolResult, ToolError, Tool |
| `runtime/llm.py` | ToolCall, ToolSpec |
| `engine/events.py` | ToolCall (inside ToolCallStart) |
| `broker/serialization.py` | ToolCall |
| `core/tools.py` | ToolSpec, Tool |
| `engine/make_tool.py` | ToolSpec, ToolResult, Tool |
| `engine/tools/delete.py` | ToolResult, ToolError |
| `engine/tools/present_file.py` | ToolResult |
| `engine/tools/read_image.py` | ToolResult |
| `engine/tools/read.py` | ToolResult |
| `engine/tools/builtin.py` | ToolError |
| `worker/adapters/slack.py` | ToolCall (indirect) |

**Tests**: update imports in `engine/engine_test.py`, `runtime/llm_test.py`; confirm pyright + pytest pass.

---

### Phase 2: Durable* rename + new types

**Goal**: Remove `Durable*` prefix and add new types (not used yet).

**`engine/types.py`** — rename:
- `DurableAssistantText` → `TextItem` (also in SessionEvent union)
- `DurableReasoning` → `ReasoningItem`
- `DurableToolCall` → `FunctionCallItem`
- `DurableSubagentStart` → `SubagentStart`
- `DurableSubagentEnd` → `SubagentEnd`
- `DurableEvent` ABC — keep
- `DurableToolResult` — keep (deleted in Phase 4)
- Update `SessionEvent` union

**`engine/types.py`** — add new types (used in later phases):
```python
@dataclasses.dataclass(frozen=True)
class FunctionCallOutput:
    content: str
    attachments: list[Attachment] = field(default_factory=list)
    images: list[ImageSource] = field(default_factory=list)  # not stored in DB, in-memory only

@dataclasses.dataclass(frozen=True)
class WebSearchCallItem(DurableEvent):
    id: str
    raw_output: dict[str, object]
    source_model: str | None = None

@dataclasses.dataclass(frozen=True)
class GeneratedImage(DurableEvent):
    id: str
    attachments: list[Attachment]
```

**`engine/events.py`** — new type:
```python
@dataclasses.dataclass(frozen=True)
class Error(DurableEvent):
    id: str
    content: str
```

**Add output field to `FunctionCallItem`** (default None, no impact on existing behavior):
```python
@dataclasses.dataclass(frozen=True)
class FunctionCallItem(DurableEvent):
    id: str
    tool_calls: list[FunctionToolCall]  # changed to single tool_call in Phase 4
    content: str | None = None
    source_model: str | None = None
    raw_output: dict[str, object] | None = None
    output: FunctionCallOutput | None = None  # new
```

**Import update targets**:

| File | Symbols changed |
|------|-------------|
| `engine/engine.py` | DurableAssistantText, DurableReasoning, DurableToolCall, DurableSubagentStart, DurableSubagentEnd |
| `runtime/llm.py` | DurableAssistantText, DurableReasoning, DurableToolCall, DurableSubagentStart, DurableSubagentEnd |
| `repos/message/store.py` | same as above + _to_session_event, _event_to_rdb_kwargs match branches |
| `broker/serialization.py` | DurableAssistantText, DurableReasoning, DurableToolResult, DurableSubagentStart, DurableSubagentEnd |
| `worker/adapters/slack.py` | DurableAssistantText, DurableToolResult |
| `worker/adapters/discord.py` | DurableAssistantText, DurableToolResult (if present) |
| `engine/context.py` | DurableToolResult |
| `engine/compaction.py` | (SessionEvent related) |

**Tests**: pyright + pytest. New types are not used yet, so existing tests only need to pass.

---

### Phase 3: Simplify Emit system

**Goal**: Remove `internal()`/buffer/flush. Add `update()`. Convert Error to durable.

**`engine/emit.py`**:
```python
@dataclasses.dataclass(frozen=True)
class Emit:
    event: Any = None
    mode: str = "ephemeral"  # "durable" | "update" | "ephemeral"

def ephemeral(event: EngineEvent) -> Emit:
    return Emit(event=event, mode="ephemeral")

def durable(event: DurableEvent) -> Emit:
    return Emit(event=event, mode="durable")

def update(event: DurableEvent) -> Emit:
    return Emit(event=event, mode="update")
```
- delete `internal()`
- delete `flush` field

**`engine/engine.py`**:
- `yield internal(TurnCompleteEvent(...), flush=True)` → `yield durable(TurnCompleteEvent(...))`
- `yield internal(FunctionCallItem(...))` → `yield durable(FunctionCallItem(...))`
- `yield internal(UnknownEvent(...))` → `yield durable(UnknownEvent(...))`
- `yield durable(..., flush=True)` → `yield durable(...)` (remove flush parameter)
- `save_error_message()` call + `yield ephemeral(TextEnd(...))` → `yield durable(Error(...))`
- remove `ErrorEnd` usage
- `TextEnd` import — keep for now (delete in Phase 5)

**`worker/engine.py`** — remove buffer logic:
```python
# Before (lines 431-450):
buffer: list[SessionEvent] = []
async for item in self.engine.run(...):
    ev = item.event
    if ev is not None:
        if isinstance(ev, DurableEvent):
            dispatch + buffer.append
        else:
            dispatch
    buffer.extend(item.internal)
    if item.flush and buffer:
        store.append(buffer)
        buffer.clear()

# After:
async for item in self.engine.run(...):
    ev = item.event
    if ev is not None:
        if item.mode == "durable":
            store.append([ev])
            dispatch(ev)
        elif item.mode == "update":
            store.update_event(ev)
            dispatch(ev)
        else:
            dispatch(ev)
```
- `save_error_message()` usage → dispatch as `Error` event
- `ErrorEnd` import → `Error` import

**`engine/events.py`**:
- delete `ErrorEnd` (replaced by Error, added in Phase 2)
- remove `ErrorEnd` from `EngineEvent` union

**`broker/serialization.py`**:
- change match branch `ErrorEnd` → `Error`

**`repos/message/store.py`**:
- add `update_event()` method (UPDATE row by id)
- add `Error` event storage support (_event_to_rdb_kwargs Error case)

**Tests**: update buffer/flush assertions in engine_test.py. Add Error emit test.

---

### Phase 4: Integrate FunctionCallItem output

**Goal**: call + output in 1 row. Delete DurableToolResult. Delete repair/interleave.

**`engine/types.py`**:
- Change `FunctionCallItem` structure:
  ```python
  @dataclasses.dataclass(frozen=True)
  class FunctionCallItem(DurableEvent):
      id: str
      tool_call: FunctionToolCall      # single (not list)
      raw_output: dict[str, object] | None = None
      source_model: str | None = None
      output: FunctionCallOutput | None = None
  ```
  - `tool_calls: list[FunctionToolCall]` → `tool_call: FunctionToolCall` (singular)
- delete `DurableToolResult`
- remove `DurableToolResult` from `SessionEvent` union
- split `ServerToolCallItemDone` from `CompletionStreamEvent`:
  - delete `ServerToolCallItemDone`
  - instead LLM client yields `WebSearchCallItem`, `ImageGenerationCallItem` (or intermediate type)

**`engine/engine.py`** — core changes:
- `ToolCallItemDone` handler:
  ```python
  case ToolCallItemDone() as item:
      fc = FunctionCallItem(
          id=uuid7().hex,
          tool_call=item.tool_call,
          raw_output=item.raw_item,
      )
      function_calls.append(fc)
      yield durable(fc)
  ```
- `ServerToolCallItemDone` handler:
  ```python
  case ServerToolCallItemDone() as item:
      yield durable(WebSearchCallItem(
          id=uuid7().hex,
          raw_output=item.raw_call_item,
          source_model=request.model,
      ))
      has_server_side = True
  ```
- `ImageItemDone` handler:
  ```python
  case ImageItemDone() as item:
      attachments = await self._save_images_to_session_data(...)
      yield durable(GeneratedImage(id=uuid7().hex, attachments=attachments))
  ```
- Tool execution loop:
  ```python
  for fc_item in function_calls:
      tool = tool_map.get(fc_item.tool_call.name)
      # ... execute ...
      updated = dataclasses.replace(fc_item, output=FunctionCallOutput(
          content=result_text,
          attachments=tool_attachments,
          images=tool_images,
      ))
      yield update(updated)
  ```
- delete `repair_orphan_tool_calls()`
- `_inject_cached_images()` — remove DurableToolResult reference (delete function itself in Phase 5)
- simplify `served_tool_call_ids` → `has_server_side: bool` flag
- On Stop, DurableToolResult → unexecuted FunctionCallItem remains output=None

**`runtime/llm.py`**:
- delete `interleave_tool_calls()`
- handle `FunctionCallItem` in `build_input_items()`:
  - if `output` exists → `function_call` + `function_call_output` pair
  - if `output=None` → `function_call` + synthetic output
- `DurableToolCall` reference → `FunctionCallItem` reference
- delete `DurableToolResult` reference

**`repos/message/store.py`**:
- `_event_to_rdb_kwargs`: update `FunctionCallItem` case (single tool_call + output)
- `_to_session_event`: existing `MessageRole.TOOL` → output inside FunctionCallItem
- delete DurableToolResult-related code

**`engine/context.py`**:
- `mask_observations()`: path `DurableToolResult.content` → `FunctionCallItem.output.content`

**`broker/serialization.py`**:
- delete DurableToolResult serialize/deserialize
- add FunctionCallItem serialize
- add WebSearchCallItem, GeneratedImage serialize

**Tests**: delete repair_orphan test in engine_test.py. Delete interleave test in llm_test.py. Add FunctionCallItem output lifecycle test.

---

### Phase 5: LLM transparency + delta pass-through + in-memory + WS protocol + Adapter + frontend

**Goal**: fix LLM client violation + engine delta pass-through + in-memory history + WS protocol switch + adapter change + simultaneous frontend migration.

Phase 5 and 6 are coupled — delta pass-through and WS protocol must change together (when engine yields ContentDelta, serialize_event must handle it).

#### Backend: LLM client

**`engine/types.py`** — redefine LLM stream events:
- add `content_index: int = 0` field to `ContentDelta`
- delete `TextItemDone` → LLM client yields `TextItem` directly
- delete `ReasoningItemDone` → LLM client yields `ReasoningItem` directly
- delete `ToolCallItemDone` → LLM client yields `FunctionCallItem(output=None)`
- delete `ImageItemDone` → LLM client yields `ImageGenerationCallItem`
- delete `UnknownItemDone` → LLM client yields `UnknownItem`
- delete `ServerToolCallItemDone` → LLM client yields `WebSearchCallItem`
- rename `StreamEnd` → `ResponseCompleted`
- add `parts` array to `TextItem` (instead of content)
- update `CompletionStreamEvent` union

**`runtime/llm.py`** — make LLM client transparent:
- `stream()`: yield completed items directly as `TextItem`, `ReasoningItem`, `FunctionCallItem`, etc.
- preserve `content_index` (include in ContentDelta)
- remove parts join → pass parts array as-is
- `ServerToolCallItemDone` → create `WebSearchCallItem` directly
- `ImageItemDone` → create `ImageGenerationCallItem` directly

#### Backend: Engine

**`engine/engine.py`** — delta pass-through:
- `ContentDelta` → `yield ephemeral(stream_event)` (pass as-is)
- `ReasoningDelta` → `yield ephemeral(stream_event)` (pass as-is)
- `ToolCallDelta` → `yield ephemeral(stream_event)` (pass as-is)
- delete `content_parts`, `reasoning_parts`, `text_group_id`, `reasoning_group_id` state
- delete `TextPartial`, `ReasoningPartial` imports

**`engine/engine.py`** — in-memory history:
- at `run()` start: `history = await self._store.list(sid)` once
- remove `await self._store.list(sid)` call inside while loop
- new event is `history.append(event)` + DB write
- DB reload only after compaction
- delete `image_cache` → `FunctionCallOutput.images` remains in in-memory history
- delete `_inject_cached_images()`

**`engine/events.py`**:
- delete `TextPartial`, `ReasoningPartial`, `TextEnd`, `ReasoningEnd`, `ToolCallStart`
- update `EngineEvent` union

#### Backend: WS protocol + Adapter

**`broker/serialization.py`** — full rewrite:
- discard integrated `type: "message"` format
- serialize with per-event unique type (see design document section 4)
- deserialize to new format too

**`worker/adapters/slack.py`**:
- `self._streamer` → `self._streamers: dict[int, ChatStream]` (per content_index)
- `ContentDelta` handler: append to `streamers[content_index]`
- `TextItem` handler: stop each streamer + metadata
- `FunctionCallItem` handler: branch on output presence for status/file upload
- delete existing `TextPartial`, `TextEnd`, `DurableAssistantText`, `DurableToolResult` handlers
- delete `_last_text` state

**`worker/adapters/discord.py`**:
- ignore delta events
- `TextItem` → separate message per part
- `FunctionCallItem` → branch by output presence into running/complete

#### Frontend

**`typescript/apps/nointern-web/`**:
- `features/chat/types.ts`:
  - discard `ChatMessageEvent`
  - new types such as `ContentDeltaEvent`, `TextItemEvent`, `FunctionCallItemEvent`
  - remove `status: "partial"/"complete"`
- `features/chat/hooks/useChatWebSocket.ts`:
  - replace `handleEvent` switch completely
  - `content_delta` → accumulate parts by `content_index`
  - `text_item` → replace with final confirmation
  - `function_call_item` → upsert by id
- `features/chat/components/MessageBubble.tsx`:
  - parts array → render multiple bubbles
- `features/chat/components/ToolCallCard.tsx`:
  - render based on `FunctionCallItem.output`

**REST API response** (`api/routes/chat.py`, etc.):
- convert history-read returned message format to match the new structure

**Tests**: substantially update LLM client tests. Rewrite serialization tests completely. Update adapter tests.

---

### Phase 6: Data migration ✅ Complete

**Goal**: convert existing DB data into new structure best-effort.

**Alembic migration** (`db-schemas/rdb/`):

1. **FunctionCallItem split** (DurableToolCall → FunctionCallItem):
   ```sql
   -- find rows where role='assistant' AND tool_calls IS NOT NULL
   -- parse tool_calls JSON array and INSERT a new row for each element
   -- match corresponding role='tool' row by tool_call_id and merge into output
   -- delete original tool_call row and matched tool row
   -- call without result → output=NULL
   -- orphan result without call → delete
   ```
   - `seq` recalculation needed (when inserting split rows between existing seq values)

2. **Server tool cleanup**:
   ```sql
   -- delete assistant row where raw_output type != 'function_call'
   -- also delete corresponding server tool DurableToolResult row
   ```

3. **GeneratedImage conversion**:
   ```sql
   -- when content='' AND attachments IS NOT NULL, change assistant row type
   -- to GeneratedImage (distinguish by role or separate column)
   ```

4. **observation_mask path change**:
   - update observation mask reference path inside compacted session `content`
   - or: keep existing compaction result as-is and use new path in future compaction

**`core/enums.py`**:
- need new values in `MessageRole`: `FUNCTION_CALL`, `WEB_SEARCH`, `GENERATED_IMAGE`, `ERROR`
- or: reuse existing `ASSISTANT`/`TOOL` role and distinguish by another column

**Note**: migration can run after Phase 4 completes. For safe rolling deploy, new code must be able to read both new structure and legacy structure. Alternative: run migration + deploy simultaneously in maintenance window.

---

## Implementation Complete Status

All Phases 1~6 were merged on 2026-03-18.

| Phase | PR | Merge date | Content |
|-------|----|--------|------|
| 1 | [#1610](https://github.com/azents/azents/pull/1610) | 2026-03-18 | `Tool*` → `FunctionTool*` rename |
| 2 | [#1611](https://github.com/azents/azents/pull/1611) | 2026-03-18 | Remove `Durable*` prefix + add new types (`WebSearchCallItem`, `GeneratedImage`, `Error`, `FunctionCallOutput`) |
| 3 | [#1612](https://github.com/azents/azents/pull/1612) | 2026-03-18 | Simplify Emit system (delete `internal()`, add `update()`, remove buffer/flush) |
| 4 | [#1613](https://github.com/azents/azents/pull/1613) | 2026-03-18 | Integrate `FunctionCallItem` call + output, delete `DurableToolResult`, delete repair/interleave |
| 5 | [#1614](https://github.com/azents/azents/pull/1614) | 2026-03-18 | LLM transparency + delta pass-through + in-memory history + WS protocol migration + adapter + frontend |
| 6 | [#1615](https://github.com/azents/azents/pull/1615) | 2026-03-18 | Data migration (DurableToolCall → FunctionCallItem row split) |

### Implementation differences from design

- No meaningful drift from the body — `FunctionCallItem` in `engine/types.py` is implemented as single `tool_call` + `output: FunctionCallOutput | None`, and `WebSearchCallItem` / `GeneratedImage` / `Error` all exist as specified.
- Only the three functions `durable()` / `update()` / `ephemeral()` exist in `engine/emit.py` (`internal()` removal confirmed).
- Follow-up correction commit: immediately after Phase 5, `fix(nointern): reload history from DB each turn to prevent infinite tool loop` (`17473f084`) temporarily restored DB reload after an infinite tool loop regression caused by introducing in-memory history. This is a compromise point with the design principle of "keep in-memory, reload only on compaction".
