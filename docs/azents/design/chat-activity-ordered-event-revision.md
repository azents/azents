---
title: "Chat Activity Ordered Event Revision"
created: 2026-07-20
updated: 2026-07-20
tags: [frontend, chat, tools, ux, testing]
---

# Chat Activity Ordered Event Revision

## Problem

The first Chat Tool Activity implementation reduced timeline item count, but its visual and information architecture do not meet the product goal:

- the collapsed activity is a large bordered card rather than a calm inline disclosure;
- the summary reports model-turn and tool-call counts instead of the kinds of work performed;
- reasoning may render outside the activity while tools render inside it;
- expansion regroups events into phases and loses the chronological relationship among reasoning, Skill use, tools, and internal control events; and
- known-tool specialization was reduced to phase labels while raw detail cards remained largely generic.

This revision follows [ADR-0174](../adr/0174-present-chat-activity-as-an-ordered-event-stream.md). It preserves ADR-0173's frontend-owned grouping while replacing its phase hierarchy. Client tool-call events add the canonical Toolkit source snapshot required for product-level summary categories.

## Goals

- Make the collapsed activity visually consistent with existing compact chat disclosures.
- Apply one ownership rule to every chat timeline event.
- Preserve exact event order across reasoning, tools, model turns, compaction, and other internal work.
- Summarize the kinds of work performed instead of implementation counts.
- Classify builtins by reviewed product intent and dynamic Toolkit tools by Toolkit product.
- Keep each presented event independently inspectable.
- Keep user-facing deliveries and actionable control surfaces discoverable.
- Preserve Generic detail as the compatibility fallback.
- Preserve presentation identity across live-to-durable replacement, resync, and pagination.

## Non-goals

- Changing provider-hosted tool payloads or client tool execution semantics beyond adding the canonical Toolkit source snapshot.
- Designing every known tool's specialized detail surface in this revision.
- Inferring Toolkit ownership from arbitrary tool-name prefixes.
- Showing Toolkit installation identity in the collapsed activity summary.
- Replacing Goal, retry, authorization, ActionExecution, or attachment components with new product-specific designs.
- Keeping the previous phase-based Activity component for historical events.

## Accepted Decisions

### Compact activity control

The collapsed activity uses the shared inline chat-control visual language instead of a `Paper` card. It is one row with a small disclosure chevron, activity icon, fixed activity label, dimmed category summary, and attention state when needed.

The collapsed row removes model-turn and tool-call counts. It does not use a border, card background, large radius, or two-line title/metadata layout.

While an activity is running, the row shows a small neutral loader and the localized `진행 중` / `Working` status next to the fixed activity label. A completed activity removes both without adding a redundant completion label. Approval, failure, or another actionable state takes visual priority over the running status and remains visible when category space is constrained.

### Collapsed category summary

Summary categories are de-duplicated in the order of their first event occurrence. Their position does not change as later events increment their counts, and a newly observed category is appended after the categories already present.

Each category counts the presented activity events assigned to it. A category with one event renders without a count; a category with two or more events renders the count after its label, such as `탐색 3`, `GitHub 2`, or `편집`. A client call and its result are one presented tool event and contribute one count. Repeated provider-tool snapshots with the same semantic call identity also contribute one count.

The summary uses the available inline width and renders only complete category segments. Categories that do not fit are represented by a final localized overflow segment: `외 N` in Korean and `+N` in English, where `N` is the number of hidden categories rather than the number of hidden events. Attention states reserve their required space before category fitting is calculated.

The activity control's accessible name exposes the full category list, counts, and current state even when visual categories overflow. The overflow segment is summary text within the activity disclosure, not a nested button or separate expansion control.

### Consistent internal-work ownership

Every presentable internal-work event between external timeline boundaries belongs to Activity. Activity may begin with reasoning, Skill use, compaction, or a tool call and may exist without any tool call.

Reasoning, Skill use, tools, compaction, Goal continuation/update control events, and other presentable internal work do not alternate between standalone and grouped presentation based on neighboring event types.

Events with no chat presentation, such as system reminders and unknown adapter output, neither create an Activity row nor split an existing Activity.

### Attachment-bearing event boundaries

Any message, client-tool event, or provider-tool event with one or more attachments renders outside Activity through its existing event component. The entire event stays outside; the projection does not extract, duplicate, or selectively promote only its attachments.

An attachment-bearing event closes the preceding activity. A later internal event starts a new activity. This replaces the current image-generation-specific deliverable projection and applies the same boundary rule to operational artifacts and user-facing files.

### Ordered expansion

The expanded activity renders `ActivityEvent[]` in transcript order. Each event owns a compact summary and independently expandable detail. No phase headings, phase aggregation, category sorting, or event de-duplication occur inside expansion.

Category de-duplication and counting apply only to the collapsed summary. Expanded Activity always preserves every presented event and repetition.

### Hybrid category ownership

Builtin tools use reviewed product categories. Toolkit-owned tools use one Toolkit product category regardless of installation. Individual event summaries expose the installation, repository, target, or other operation-specific context when relevant.

Accepted labels:

| Scope | Korean | English |
| --- | --- | --- |
| Skill application | `Skill` | `Skill` |
| Information inspection, search, and research | `탐색` | `Explore` |
| Shell command and stream interaction | `Shell` | `Shell` |
| File creation, editing, and deletion | `편집` | `Edit` |
| File import and export | `파일` | `File` |
| Image generation | `이미지` | `Image` |
| Memory reads and mutations | `Memory` | `Memory` |
| Goal and Todo management | `계획` | `Organize` |
| Subagent lifecycle and communication | `서브에이전트` | `Subagent` |
| Unclassified builtin fallback | `기타` | `Other` |
| Toolkit-owned tools | Toolkit product name | Toolkit product name |

Curated English action categories use one-word verbs. Product concepts, resource types, and fallback labels use nouns. Toolkit product categories preserve their canonical display names and are not forced into the one-word convention.

### Canonical Toolkit source snapshot

A DB-attached client tool call carries an optional immutable `toolkit_source` snapshot:

```text
ToolkitSourceSnapshot
  toolkit_config_id
  toolkit_type
  toolkit_name
  toolkit_slug
```

`toolkit_config_id` is the collapsed-summary grouping key, and `toolkit_name` is the display label captured at call time. Multiple installation-specific tools exposed by the same ToolkitConfig therefore share one category. The other fields support diagnostics and stable rendering after configuration changes.

Builtin and auto-bound client tools have no `toolkit_source` and use the explicit builtin category registry. The engine resolves the snapshot from the exact `ToolCatalog` entry used for the final model-visible tool name. Frontend code must not infer it from a prefix or query current Toolkit configuration to reinterpret a historical event.

The source snapshot is persisted on the durable client tool-call event and on active-tool-call state used to reconstruct live projections. Durable and live forms expose the same fields so replacement does not change category identity or labels.

Pre-contract client tool-call events remain in the revised ordered Activity presentation. If a source-less historical call has an exact known builtin name, it uses the builtin registry; otherwise it uses `Other`. The projection does not parse legacy prefixes, query current Toolkit configuration, or retain the previous Activity component for historical events.

### Tool-specific detail design sequencing

The common ordered event row and disclosure behavior are designed and implemented first. Tool-specific detail presentations are discussed only after this revision is validated. This deferral does not remove tool-specific presentation from the product roadmap.

## Complete Timeline Ownership

The following matrix defines the complete ownership and boundary contract for chat timeline presentation.

| Source | Draft presentation | Activity effect |
| --- | --- | --- |
| User message or action input | Existing user/input surface outside Activity | Close preceding Activity; later internal work starts a new one. |
| Agent mailbox message projected as user input | Existing mailbox message outside Activity | Close preceding Activity. |
| Visible assistant text | Existing assistant message outside Activity | Close preceding Activity. |
| Any attachment-bearing message or tool event | Existing owning event component outside Activity | Close preceding Activity before the event. |
| Reasoning | Activity event | Start or append to Activity. |
| Skill loaded | Activity event using the existing Skill disclosure | Start or append to Activity. |
| Client tool call/result without attachments | One Activity tool event anchored at call position | Start or append; result updates without reordering. |
| Provider tool call without attachments | One Activity tool event per semantic call identity | Start or append; snapshots update in place. |
| Compaction marker/summary | One Activity compaction event anchored at start | Start or append; summary completes the event. |
| Goal continuation or Goal update control event | Activity control event | Start or append to the next work period. |
| Turn marker | Activity metadata only | Update usage/turn state without adding a row or splitting. |
| Run marker | Activity lifecycle metadata only | Finalize the current open Activity; add no row. |
| Hidden system reminder or unknown adapter output | No chat presentation | Do not create or split Activity. |
| Todo/subagent tree invalidation | Existing non-transcript UI state | Do not create or split Activity. |
| Authorization request | Compact action attached to the latest open Activity in latest-following mode | Set attention state; if no open Activity exists, retain the existing standalone authorization surface. |
| Tool-level failed/cancelled/interrupted status | The owning tool event inside Activity | Set Activity attention state without moving the event. |
| Account-link nudge | Existing standalone actionable surface | Close preceding Activity. |
| Goal briefing | Existing briefing card outside Activity | Close preceding Activity. |
| ActionExecution live/durable projection | Existing operation card outside Activity | Close preceding Activity. |
| Run-level system error and retry UI | Existing error/retry surface outside Activity | Close and mark preceding Activity failed when related. |
| User interruption notice | Existing interruption surface outside Activity | Close preceding Activity. |

Every timeline source now has a defined presentation owner and boundary effect.

## Backend Data Contract

### Toolkit source propagation

Extend runtime source metadata rather than parsing the final tool name:

1. `ToolkitBinding` retains the source ToolkitConfig ID, type, display name, and slug for DB-attached bindings.
2. `ToolCatalogSource` carries those fields with each final model-visible tool entry.
3. When normalized model output selects a client tool name, the engine looks up that exact catalog entry and copies its optional source snapshot into `ClientToolCallPayload`.
4. The same snapshot is copied into `ActiveToolCall` before it is stored in `agent_runs.active_tool_calls`.
5. `active_tool_call_to_live_event()` exposes the snapshot on live client tool-call events.
6. Durable event serialization, public API schemas, TypeScript types, and generated clients expose the same optional object.

The active-call column is JSONB, so the source snapshot does not require a relational column migration. Existing JSON objects and historical events omit the optional object and use the accepted historical fallback.

### Payload shape

The conceptual client call payload becomes:

```text
ClientToolCallPayload
  call_id
  name
  arguments
  toolkit_source?  # absent for builtin, auto-bound, and pre-contract events
```

`ClientToolResultPayload` does not duplicate the source snapshot. It joins the call by `call_id`, and the call event remains the source of presentation identity.

Provider-hosted tool calls remain provider builtins and do not use Toolkit source metadata.

## Frontend Projection Architecture

### Canonical inputs

Build timeline presentation from the state already owned by `useChatSessionContainer`:

- ordered durable `historyEvents`;
- ordered latest-following live partial events after semantic counterpart removal;
- live Run state and phase;
- durable/live ActionExecution projections;
- authorization and account-link actions; and
- pending input surfaces.

Do not build Activity from the current `ChatMessage[]`. `ChatMessage` merges client call/results and stores provider calls, reasoning, and attachments in separate fields, so it cannot be the canonical ordered heterogeneous source.

### Normalization

Normalize durable and live events into one ordered `TimelineEvent[]` before rendering:

```text
TimelineEvent
  semantic_key
  source_event_ids
  timeline_position
  kind
  payload
  status
  attachments
  optional_category
  presentation_owner
```

Use the existing semantic identity rules behind `eventRenderKey()` for live-to-durable equivalence. Extend the normalizer rather than introducing a second incompatible identity function.

Normalization rules:

1. Keep the server-provided durable array order.
2. Append visible live partial events in their maintained partial-history order only in latest-following mode.
3. Remove live events with a durable semantic counterpart before normalization.
4. Pair `client_tool_result` with `client_tool_call` by `call_id` and anchor the presented event at the call position.
5. Update repeated provider-tool snapshots by semantic call identity and retain the first observed position.
6. Fold compaction start and summary by `compaction_id` and anchor at the start marker.
7. Keep unmatched result/summary records as pending joins rather than rendering them at a false position.
8. Project ActionExecution independently using its durable history event identity or live projection timestamp.

### Ownership and grouping pass

Run one left-to-right projection over normalized events:

1. Metadata-only or hidden events update state and do not flush.
2. Internal Activity events start or append to the current group.
3. An attachment-bearing event flushes the current group, renders outside it, and leaves no group open.
4. Any other external boundary flushes the current group and renders outside it.
5. A run terminal marker finalizes an open group without creating a visible row.
6. End of loaded input flushes the open group as a potentially partial Activity.

The pass emits:

```text
ChatPresentationItem =
  ActivityPresentationItem
  | MessagePresentationItem
  | ToolPresentationItem
  | ControlPresentationItem
  | ActionExecutionPresentationItem
```

An attachment-bearing tool uses `ToolPresentationItem` and reuses `ToolCallCard` or `ProviderToolCallCard` outside Activity. The image-generation-specific `ToolDeliverablePresentationItem` is removed.

### Activity model

```text
ActivityGroup
  id
  anchor_event_key
  source_event_keys
  start/end timeline positions
  ordered ActivityEvent[]
  category summary
  lifecycle state
  attention state
  usage
  is_window_partial

ActivityEvent
  semantic_key
  reasoning | tool | skill | compaction | goal-control | other
  stable source identity
  compact summary
  existing detail component ownership
  optional category
  status
```

A client call/result pair is one `ActivityEvent`. Category counts therefore reflect user-visible event rows rather than raw transcript record count.

### Stable Activity identity

Use the first internal event's semantic key as the Activity anchor. Live-to-durable replacement preserves that key through existing counterpart rules.

Pagination may reveal an earlier internal event before the current loaded anchor. When re-projection extends an Activity backward, migrate expansion state to the new group that contains the previous anchor key. Do not store expansion state only by the transient React key.

Forward streaming appends events without changing the anchor. Arrival of a closing boundary changes lifecycle state but does not replace the Activity identity.

### Pagination and detached history

Page boundaries are not Activity boundaries.

- Prepending older durable events re-runs normalization and grouping across the complete loaded durable window.
- Loading newer events in detached history performs the same re-projection without including latest-only live events.
- An Activity touching the oldest or newest loaded edge sets `is_window_partial` when the adjacent boundary is unknown.
- Partial status affects only internal diagnostics and test assertions; it does not add user-facing copy in this revision.
- Category counts and ordered events may grow when another page extends a partial Activity.
- Expansion state survives extension through anchor containment migration.

### Resync and live replacement

REST resync remains authoritative. The projection consumes the post-resync durable array and live taxonomy snapshot rather than maintaining an Activity-specific cache.

- `partialHistoryEventMatchesDurableEvent()` removes live counterparts.
- The same semantic key keeps event and category identity stable.
- Client tool status and attachments update on the paired event without moving it.
- Provider tool snapshots update in place.
- Toolkit category identity stays stable because active and durable calls carry the same `toolkit_source` snapshot.
- A stale REST snapshot rejected by the existing epoch/generation guard cannot roll Activity backward.

## Category Resolution

Resolve a category after event normalization:

1. Skill events use `Skill`.
2. A client tool with `toolkit_source` uses `toolkit_config_id` as category identity and the stored `toolkit_name` as its label.
3. A source-less client tool uses the exact builtin registry.
4. An exact known builtin with no reviewed mapping uses `Other`.
5. Every other source-less client call, including pre-contract Toolkit calls, uses `Other`.
6. Provider-hosted tools use the provider builtin registry.
7. Reasoning, compaction, and control events may have no category unless the accepted taxonomy assigns one.

Category state stores identity separately from localized label:

```text
ActivityCategory
  key
  label_key_or_snapshot
  first_event_index
  count
```

Increment count once per presented Activity event. Never recalculate order from descending count or completion time. Events without a category do not contribute a summary segment; a reasoning-only or otherwise uncategorized Activity renders the fixed Activity label without an empty placeholder.

## Compact Summary Layout

The row layout consists of:

1. disclosure chevron;
2. Activity icon;
3. fixed localized Activity label;
4. optional running status;
5. flexible category summary;
6. optional attention/action state.

Measure the available summary width after fixed and attention regions. Use `ResizeObserver` on the row and a hidden measurement container with the production font and styles. Select the longest prefix of complete category segments that fits together with the overflow segment when required.

Do not use CSS text truncation to cut a category label or count. Recalculate on width, locale, category, count, font, or attention-state changes. Server rendering may render the full accessible name and a conservative visual prefix; hydration performs the measured fit without changing event ownership or expansion state.

## Expanded Event Rendering

Expansion renders the existing component owned by each normalized event:

- reasoning disclosure for reasoning;
- Skill disclosure for `skill_loaded`;
- tool cards for client/provider tools;
- compaction disclosure for compaction;
- compact Goal control disclosure for Goal continuation/update; and
- Generic event disclosure for any newly presentable internal event without a specialized component.

The Activity container provides vertical spacing and an ordered list only. It does not add phase headings, nested cards, or a second disclosure around an event component that already owns its detail expansion.

Activity remains collapsed by default. New streaming events, status changes, failures, and authorization requests never force it open. User-controlled expansion persists while the same Activity anchor remains loaded.

## Lifecycle and Attention

### Running and completion

The latest open Activity is running when the latest-following live Run is active and the Activity belongs to the current unclosed internal-work segment. A running Activity shows the neutral loader and status.

A terminal run marker or external boundary completes the Activity. Completion removes the loader/status without adding success copy.

### Tool failures

A failed, cancelled, or interrupted tool remains at its chronological position. The Activity summary exposes the highest-priority relevant attention state, but expansion remains user-controlled.

### Authorization

Authorization is live actionable state rather than a durable transcript event. Attach it only to the latest open Activity in latest-following mode. The compact action remains visible without expansion and reserves width before categories are fitted.

If no open Activity exists, keep the existing standalone authorization surface. Multiple pending authorization requests retain their current list order; only the first may occupy the Activity compact action, and the remainder stay standalone until the preceding request clears.

Authorization does not create a synthetic ordered event because the current event has no call identity or durable transcript position.

### Run-level failure, retry, interruption, Goal briefing, and ActionExecution

The accepted external-boundary rule applies consistently:

- run-level errors and retry UI remain standalone;
- interruption notices remain standalone;
- Goal briefing remains a standalone result card; and
- ActionExecution remains a standalone operation card.

A related open Activity completes before the standalone item and may retain a failure attention state. This keeps actionable or result-oriented surfaces discoverable without expanding the default-collapsed Activity.

## Attachment Handling

Collect attachments from canonical event content rather than from tool specialization:

- user/assistant event attachment arrays;
- attachment output parts;
- client tool-result output parts joined to the call;
- provider semantic output attachment parts; and
- any future normalized event attachment field.

If the normalized presented event owns at least one attachment, classify the entire event as external before Activity grouping. Do not hide attachment URIs from a duplicated internal tool card because no duplicated card exists.

Existing file gallery, preview, availability, download, and adaptive image behavior remain owned by the event component. Unknown or malformed attachment metadata follows the existing file presentation fallback.

## Migration and Rollout

1. Add optional Toolkit source models and propagation to runtime catalog, client call events, active calls, live projections, API schemas, and generated clients.
2. Add contract tests proving live and durable source snapshot equality.
3. Introduce the ordered event normalizer and projection tests without switching the rendered component.
4. Replace phase-based Activity rendering and remove image-specific deliverable extraction.
5. Add compact category fitting, accessibility state, and visual stories.
6. Add deterministic web-surface E2E coverage.
7. Update living conversation, Toolkit, file-exchange, and execution-loop specs in the implementation PR.

No backfill migration is attempted for historical events. Existing active-call JSON without `toolkit_source` remains valid and uses the historical fallback. No legacy phase-based UI branch remains after rollout.

## Feasibility Matrix

| Requirement | Result | Evidence and required work |
| --- | --- | --- |
| Ordered reasoning, Skill, compaction, and tool presentation | Feasible | Durable `historyEvents` and ordered live partial events already exist before `ChatMessage` mapping. Build the new projection at that layer. |
| Live-to-durable identity | Feasible | Existing `eventRenderKey()` and counterpart removal provide semantic roots for reasoning and tool events; extend the same normalization. |
| Client call/result chronology | Feasible | Join by `call_id` and anchor at the call position instead of using the current message merge as presentation order. |
| Provider tool snapshot chronology | Feasible | Provider calls already carry stable `call_id`; update by semantic identity at first position. |
| Skill and compaction inclusion | Feasible | Durable `skill_loaded`, `compaction_marker`, and `compaction_summary` events already reach the frontend. |
| Attachment-bearing boundaries | Feasible | Message, client-result, and provider semantic projections already expose attachment lists. |
| Compact row, overflow, and attention priority | Feasible | Existing inline controls, ResizeObserver-capable web UI, run state, tool status, and authorization state provide the required inputs. |
| Toolkit product categories for new calls | Feasible after accepted contract change | Runtime `ToolCatalogSource` already owns slug/type/display metadata; retain ToolkitConfig ID/name and copy the snapshot into client call and active-call records. |
| Historical Toolkit categories | Feasible with accepted fallback | Exact builtin mapping plus `Other`; no inference or UI fork. |
| Pagination and detached history | Feasible | The container owns merged durable pages and newer/older cursors; re-project the complete loaded window and migrate expansion by anchor containment. |
| REST/WebSocket resync | Feasible | Existing snapshot epoch/generation guards and semantic counterpart removal remain authoritative. |
| Deterministic verification | Feasible | Existing E2E substrate covers reasoning, client/provider tools, compaction, attachments, and persistence; add one composed web-surface scenario and projection fixtures. |
| User-visible control/result ownership | Feasible with accepted boundary | Keep error/retry, interruption, Goal briefing, and ActionExecution outside Activity; retain tool-level failures and authorization attention inside. |

## Non-blocking Implementation Follow-ups

### Remaining builtin mapping

Validate every actual builtin against the accepted categories. `code_interpreter` must not be assigned to `Shell` merely because both execute code. Any builtin without an accurate accepted category remains `Other`; mapping completeness does not block the container revision.

### Event summary names

Reasoning, compaction, Goal controls, authorization, and each common builtin need concise event-row summaries. These names are separate from activity category labels and can be reviewed as reversible presentation copy during implementation.

### Specialized tool detail

Known tools may later replace Generic detail through the presentation registry. This work does not change Activity ownership, order, category, or boundary rules.

## Test Strategy

### Backend contract tests

- DB-attached catalog entries retain ToolkitConfig ID, type, name, and slug.
- Normalized client calls receive the exact source snapshot from their selected catalog entry.
- Builtin and auto-bound calls omit `toolkit_source`.
- Active-call JSON round-trips the source snapshot.
- Live and durable client call payloads expose identical source fields.
- Toolkit rename, detach, or deletion after the call does not change durable presentation identity.
- Old events and active-call JSON without the object remain readable and source-less.

### Frontend normalization and projection tests

- reasoning-only work creates Activity;
- reasoning before, between, and after tools remains ordered;
- Skill and compaction start Activity without a tool;
- client call/result pair renders once at the call position;
- provider snapshots render once at the first position;
- category calculation never reorders events;
- repeated categories de-duplicate only in the collapsed summary;
- multiple installation-specific calls sharing one ToolkitConfig contribute one product category;
- source-less historical calls use exact builtin mapping or `Other` without prefix inference;
- hidden metadata events do not split Activity;
- turn/run markers update metadata without adding event rows;
- message, client-tool, and provider-tool attachments keep the entire owning event outside Activity;
- an attachment-bearing event closes the preceding Activity and later internal work starts another;
- page prepend/append extends groups without treating the cursor as a boundary;
- expansion survives backward extension by anchor containment;
- live-to-durable replacement preserves event identity, category, status, and order;
- detached history excludes latest-only live events; and
- stale REST snapshots cannot roll the projection backward.

### Component and visual verification

Render the real component through Storybook or the app surface under production providers and fonts.

Required states:

- collapsed and expanded;
- short and overflowing category summaries;
- reasoning-only Activity;
- mixed builtin and Toolkit Activity;
- source-less historical `Other` call;
- running, tool-failed, and authorization-required states;
- attachment boundary before and after Activity;
- partial loaded-window Activity;
- desktop and narrow mobile;
- light and dark themes; and
- Korean and English locales.

Compare the collapsed row against existing inline chat disclosures for height, typography, chevron placement, spacing, and visual weight. Capture native-resolution screenshots and confirm no horizontal overflow or category fragment clipping.

### Accessibility verification

- the activity control exposes button semantics and expanded state;
- the accessible name includes the complete category list, counts, running state, and attention state;
- every event disclosure is independently keyboard operable;
- DOM order matches transcript order;
- visual overflow does not remove category information from the accessible name;
- authorization remains keyboard reachable without expanding Activity;
- attention changes are announced without forcing expansion; and
- focus does not reset when live events append or a partial group extends through pagination.

### Primary deterministic E2E verification

Use a composed Main Web scenario containing:

1. reasoning before the first tool;
2. Skill use;
3. alternating reasoning and builtin calls across multiple model turns;
4. Toolkit calls from multiple installations of one ToolkitConfig;
5. compaction;
6. a tool attachment boundary;
7. later internal work;
8. a visible assistant delivery boundary;
9. refresh/resync; and
10. older/newer page extension across an Activity boundary.

Verify exact expanded order, collapsed category order/counts, attachment ownership, stable live-to-durable identity, refresh equivalence, and a new Activity after each external boundary.

### CI policy

Run backend ruff, pyright, and focused pytest; regenerate OpenAPI clients; run web format, lint, typecheck, unit tests, and Storybook build; run deterministic browser checks and the required web-surface E2E job. Docker-dependent full-stack validation may be delegated to CI when unavailable locally, but no local full-stack pass may be claimed in that case.

## Implementation Phases

1. **Toolkit identity contract** — backend catalog, event/active-call payloads, OpenAPI, generated clients, and contract tests.
2. **Ordered projection** — raw event normalizer, pairing, ownership pass, pagination/resync identity, and projection tests.
3. **Activity UI** — compact control, summary fitting, ordered event list, attention/lifecycle state, and removal of phase/deliverable projection.
4. **Verification and specs** — component visuals, accessibility, deterministic E2E, and living-spec updates.

The phases may be delivered as a stack because the backend contract can land independently before the frontend consumes it. Create the complete PR stack before waiting on CI.

## Finalization Criteria

The design is final because:

- the user-visible control/result boundary is recorded in ADR-0174;
- the ownership matrix contains no unresolved row;
- the feasibility matrix contains no `blocked` result;
- the design and ADR agree on Toolkit source, historical fallback, attachment and control boundaries, summary overflow, and ordered expansion; and
- implementation remains gated on explicit approval.
