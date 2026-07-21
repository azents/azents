---
title: "Chat Live State Separates Partial History from Other Live State"
created: 2026-06-10
tags: [architecture, backend, frontend, chat, streaming, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: live-260610
historical_reconstruction: true
migration_source: "docs/azents/adr/0054-live-state-partial-history-taxonomy.md"
---

# live-260610/ADR: Chat Live State Separates Partial History from Other Live State

## Status

Accepted. [chat-260604/ADR](./chat-260604-chat-protocol-history-live.md) and [live-260604/ADR](./live-260604-live-history-projection-handoff-and-stream-batching.md) defined the boundary between durable history and non-durable live state, but did not sufficiently specify subcategories inside live state. As a result, streaming partials, tool calls, input buffers, and session/run state still became mixed in the same live path. This ADR fixes live-state internal taxonomy and API/state-management separation rules as a follow-up decision.

## Background

Chat protocol separates persisted canonical history and non-durable live state. However, live state is not one homogeneous kind of state. Current live state contains values with different lifecycles:

- State shown in chat timeline as assistant-side items during a run but not yet finalized as durable history, such as assistant text partial, reasoning partial, and tool call without result.
- Current session/run/UI control state, such as session run state, run phase, model call waiting, input buffer, stop pending, and authorization request.

The first group is an unresolved history candidate shown in chat timeline and should naturally hand off to a durable counterpart during run progression. The second group is not a timeline history candidate; it is overwritten as latest snapshot or used only as UI control state.

If both are handled through the same `live.items` or frontend reducer path, these problems occur:

- Partial assistant/reasoning/tool call is not semantically connected to its durable counterpart and depends on event-id removal.
- General live state such as input buffer or run state flows through the same path as timeline projection.
- Tool call without result is partial history, but if provisional function-call delta and runtime active tool state are mixed, unnamed tool cards, stale running cards, or cards without results can remain.
- Frontend immediately converts live canonical events into `ChatMessage`, losing lifecycle information about whether the item is partial history, other live state, or durable history.

Therefore, keep live state as a first-class concept, but clearly separate partial history and other live state inside it at API level and frontend state-management level.

## Decisions

These decisions are referenced by stable IDs in implementation and SPEC.

- live-260610/ADR-D1: Live state has partial history and other live state as subcategories.
- live-260610/ADR-D2: Partial history is an assistant-side unresolved history candidate rendered in chat timeline before it naturally becomes durable history during a run.
- live-260610/ADR-D3: Tool call without result is included in partial history.
- live-260610/ADR-D4: Input buffer, session run state, model call waiting, run phase, and similar states are other live state, not partial history.
- live-260610/ADR-D5: API responses and WebSocket actions express partial history and other live state separately.
- live-260610/ADR-D6: Frontend state management separates partial history collection from other live state object.
- live-260610/ADR-D7: Durable history handoff cleans up partial history by semantic key, not event id.
- live-260610/ADR-D8: Frontend live state uses one managed state object as source of truth, and WebSocket events render the result of mutating this object.
- live-260610/ADR-D9: Partial history is an ordered collection and preserves WebSocket patch application order plus semantic merge order with existing partials.
- live-260610/ADR-D10: History and partial history are managed by independent containers, and rendering is composed by a stateless composite container.

### 1. Define live state taxonomy

Chat live state has these two subcategories.

#### Partial history

Partial history is an assistant-side unresolved history candidate rendered in chat timeline before naturally becoming durable history during a run. It is not yet finalized as durable canonical history, but users see it like history at the latest tail.

Examples:

- Streaming assistant text
- Streaming reasoning
- Tool call without result
- Running card for provider/client tool call
- Future assistant-side intermediate items that converge to durable counterpart during a run

Partial history must have these properties:

- It needs timeline ordering.
- It needs semantic key connected to durable counterpart.
- In latest-following screen, it is composed and rendered below durable history tail.
- In detached history browsing screen, it is not rendered.
- When durable counterpart arrives, it is removed, replaced, or handed off into complete view model.
- During run progression, it naturally hands off to durable history when durable counterpart appears.

#### Other live state

Other live state represents current session/run/input/control state and is not an unresolved chat timeline history candidate.

Examples:

- Session run state
- Agent run phase
- Model call waiting / response pending state
- Input buffer
- Stop pending
- Authorization request
- Compaction ongoing flag
- Client-local state such as subscription health, reconnect, buffering

Other live state has these properties:

- It does not need timeline ordering.
- It is not a durable history handoff target.
- It is overwritten or replaced by latest snapshot or WebSocket update.
- It is used for buttons, badges, pending indicators, queue UI, and other control/view state.

### 2. Tool call without result is partial history

Tool call without result is an unresolved assistant-side action shown in chat timeline. Therefore it belongs to partial history.

However, if function-call argument delta is still provisional and has not finalized call id or tool name, do not expose it as renderable partial history item immediately. Backend or frontend reducer must choose one of these:

- Keep it only in internal buffer until call id and name are finalized.
- Keep explicit provisional state but do not render it as normal timeline card.

When tool result arrives as durable history, hand off the matching partial tool call by semantic key into complete tool call/result view.

### 3. API responses separate partial history and other live state

Chat REST snapshot does not represent live state as a single `items` bag. At API level, distinguish at least:

- `live.partial_history.items`: assistant-side unresolved timeline candidates
- `live.input_buffers`: pending user input queue
- `live.run`: current run projection
- `live.session_run_state`: session runtime run state
- If needed, `live.model_call_waiting`, `live.authorization_requests`, `live.flags`

Do not keep existing aggregate `live.items` bag. Frontend state management uses only explicitly separated fields as source of truth and does not keep `live.items` or `snapshot.live_events` fallback.

### 4. WebSocket actions distinguish partial history update and live state update

WebSocket contract must semantically distinguish partial history from other live state updates. Even if implementation keeps existing action envelope names for compatibility, payload must immediately be routed to exactly one taxonomy reducer:

- Partial history upsert
- Partial history removal
- Input buffer/live control state update
- Durable `history_event_appended`

Frontend must classify live update into either partial history reducer or live state reducer immediately, and must not process it like durable history event in the same handler.

### 5. Frontend state management separates partial history collection and live state object

Frontend does not scatter live state into one `messages` array or arbitrary boolean flags. Minimum state model has this separation:

- Durable history collection
- Managed live state object
  - Partial history collection
  - Other live state object
  - Pending input buffer collection
- Chat view ADT: latest following / detached history browsing

Managed live state object is the source of truth for frontend live state. WebSocket live events are treated as patches mutating this object, and REST live snapshot is input that replaces or reconciles the authoritative baseline of the same object. UI does not render WebSocket events directly; it renders selector output derived from managed live state object.

Rendering happens in selector:

- Latest following: compose durable history tail with partial history inside managed live state to build timeline.
- Detached history browsing: do not compose partial history into timeline; show only new activity indicator based on managed live state.
- Pending input buffer is displayed as user-side queue and is not included in partial history.

Partial history item preserves `partial` lifecycle. Only durable history event is treated as `complete` lifecycle. Do not convert live assistant/reasoning/tool partial into `complete` message and lose lifecycle information.

### 6. WebSocket events mutate managed live state

Frontend does not treat WebSocket live events as rendering commands. WebSocket event is a mutation or patch applied to managed live state object.

Rules:

1. `partial_history_upserted` or legacy `live_event_upserted` classified as partial history upserts into managed live state's partial history collection.
2. `partial_history_removed` or legacy `live_event_removed` classified as partial history removes from managed live state's partial history collection.
3. Updates such as session run state, run phase, model call waiting, input buffer, and authorization request mutate other live state area in managed live state.
4. Rendering uses only view model produced by selector after mutation.
5. REST snapshot apply and WebSocket patch apply share the same live state reducer rules instead of separate ad-hoc setState paths.

This decision also applies across replay/buffering/reconnect boundaries. When replaying buffered WebSocket events, apply them sequentially to managed live state object and render selector result, rather than appending events directly to UI.

### 7. Partial history is managed as ordered collection

Partial history is rendered in chat timeline, so order is part of domain meaning. Frontend managed live state does not manage partial history only as unordered map. Internal lookup may use semantic key map, but render collection must preserve stable ordering.

WebSocket patch rules:

1. When new partial history item arrives, append it to current partial history tail.
2. When patch with same semantic key as existing partial history item arrives, keep existing position and merge or replace payload only.
3. Patches received on the same WebSocket connection are applied to managed live state in receive order.
4. When replaying buffered patches, preserve buffer insertion order.
5. When building baseline from REST live snapshot and replaying buffered patches, use snapshot ordering as baseline and append or merge according to patch order.
6. When removing partial item on durable history handoff, do not reorder remaining partial history items.

Partial history merge is not based only on event id. Assistant text, reasoning, and tool call without result find existing partial by semantic key. A patch with same semantic key updates the same partial history item. A patch with different semantic key is a new timeline candidate.

To separate ordering and merge, partial history state needs at least:

- `order`: ordered id/key list representing render order
- `itemsByKey`: map for finding partial item by semantic key

Implementation need not use this exact shape, but must satisfy the same invariants.

### 8. History and partial history are composed by stateless composite container

History and partial history have different lifecycles and are managed by independent containers.

- History container manages durable history list.
- Partial history container manages partial history list inside managed live state.
- Composite container composes output history lists from the two containers for rendering.

Composite history is not separate stored state. Composite container creates only derived state by stateless selector such as `useMemo` combining history output and partial history output. Do not store composite result as source of truth or apply WebSocket patches directly to composite list.

Composite merge rules:

1. Order is durable history list followed by partial history list.
2. Relative order of durable history list is decided by history container.
3. Relative order of partial history list is decided by partial history container.
4. Composite container does not infer new cross-container ordering.
5. If same unique id exists in both durable history and partial history, skip partial history item.
6. Rendering key uses item's unique id.

This dedup is a safety net at composite stage for natural rendering handover. If durable history and partial history share same id, React key can be preserved or naturally replaced by same key. If ids differ but semantic key matches, composite container does not infer that handoff. In that case, partial history reducer or durable handoff reducer must first clean up partial history by semantic key.

Responsibility boundary:

- History container: manages durable history source of truth.
- Partial history container: manages live partial history source of truth, ordering, semantic merge, semantic handoff.
- Composite container: stateless append of two output lists + id dedup + render key.

### 9. Durable handoff uses semantic key

Partial history item and durable counterpart can have different event ids. Therefore handoff must not depend only on event-id removal.

Partial history item must have at least these semantic keys:

- Assistant text: session + content index or model output item id
- Reasoning: session + reasoning stream id or turn-local reasoning key
- Tool call: call id. Before call id is finalized, do not expose as renderable partial history.

When durable history event is appended, frontend selector or reducer removes matching semantic-key partial history or replaces it with complete representation. Backend also removes partial history from live store when persisted counterpart appears, but frontend stability must not rely only on receiving remove event.

## Rejected Directions

### Treat live state and partial history as opposing concepts

Rejected. Partial history is not a separate concept outside live state; it is a live state subcategory. The important point is taxonomy inside live state.

### Keep putting every non-durable projection in `live.items` bag

Rejected. A single bag hides lifecycle differences between assistant-side timeline candidates and session/input/control state. Keep only during compatibility period; new state management uses separated fields or reducer classification.

### Hide tool call without result

Rejected. Tool call without result is partial history. However, provisional deltas with incomplete call id/name must not be rendered as normal tool cards.

### Clean up live partials only by event id

Rejected. Partial history and durable counterpart can have different ids. Even if remove event is lost or reordered, state must converge by semantic key.

### Manage partial history only as unordered map

Rejected. Partial history is live state rendered in chat timeline, so order matters. A map may be used for lookup optimization, but an ordered collection or equivalent ordering invariant is required for rendering order.

### Store composite history as separate mutable state

Rejected. Composite history is derived state composed from history container and partial history container output for rendering. Storing it as separate mutable state adds another source of truth and recreates problems where WebSocket patch, REST snapshot, and handoff update different lists.

### Infer semantic handoff inside composite container

Rejected. Composite container only performs stateless append and id dedup. Semantic handoff between items with different ids is responsibility of partial history reducer or durable handoff reducer.

### Treat input buffer as partial history

Rejected. Input buffer is user-side pending queue, not assistant-side unresolved history candidate. It is live state but not partial history.

## Consequences

### Expected Benefits

- Lifecycle of timeline candidates and control/session state becomes clear inside live state.
- Partial assistant/reasoning/tool call hand off reliably to durable counterparts.
- Tool call without result is represented as correct partial history while preventing provisional tool card exposure.
- Input buffer, session run state, and model call waiting no longer mix with timeline partials.
- Detached history browsing can clearly disable partial history rendering, while latest following can compose it.
- History and partial history keep independent sources of truth while rendering naturally hands over through stateless composite.

### Cost and Risks

- REST schema and generated client changes are needed.
- During WebSocket action compatibility period, old/new actions or classification reducers must coexist.
- Frontend `messages`-centered state must be restructured into durable history and managed live state object.
- WebSocket event handler and REST snapshot apply path must be unified under same live state reducer rules.
- Reducer structure must satisfy both partial history ordering and semantic-key merge.
- Frontend state boundary must stay clear so composite container remains stateless derived state.
- Semantic key design must align with provider-specific canonical event mapping.
- Tool call provisional buffering policy must be implemented clearly.

## Related Documents

- [chat-260604/ADR: Chat protocol uses canonical event history/live API](./chat-260604-chat-protocol-history-live.md)
- [live-260604/ADR: Define chat live/history handoff and streaming partial batching](./live-260604-live-history-projection-handoff-and-stream-batching.md)
- [chat-260609/ADR: Chat session resync converges to history/live state after subscribe ack](./chat-260609-chat-resync-scroll.md)

## Migration provenance

- Historical source filename: `0054-live-state-partial-history-taxonomy.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
