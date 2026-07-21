---
title: "Present Chat Activity as an Ordered Event Stream"
created: 2026-07-20
tags: [architecture, frontend, chat, tools, ux, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: chat-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0174-present-chat-activity-as-an-ordered-event-stream.md"
---

# chat-260720/ADR: Present Chat Activity as an Ordered Event Stream

## Context

[group-260720/ADR](./group-260720-group-chat-activity-in-the-frontend.md) moved continuous chat tool work into a frontend-owned `Activity` presentation, but the implemented presentation introduced three problems:

1. the collapsed activity uses a large bordered card that visually dominates the conversation;
2. its summary exposes implementation counts such as model turns and tool calls instead of the kinds of work performed; and
3. expansion regroups calls into semantic phases, separating reasoning from tools and destroying the original event order.

Reasoning and other internal work events are also projected inconsistently: an event may appear inside or outside an activity depending on whether a tool group already exists. The product requires one predictable rule for all internal work events.

The activity summary must support first-party builtins without hard-coding every dynamically installed Toolkit tool. Toolkit products may also have multiple installations, but installation identity is detail rather than top-level activity-summary information.

## Decision

### Treat Activity as a continuous internal-work stream

The frontend activity projection starts from the first internal work event, not from the first tool call. All internal work events between user-visible delivery boundaries belong to the activity regardless of event type. This includes reasoning, Skill use, client and provider tool calls, compaction, and other internal control events that receive chat presentation.

Reasoning does not render as a separate Thinking block when it belongs to an activity. A reasoning-only work period can create an activity without any tool call.

User-visible messages and deliverables remain outside activity and separate adjacent work periods. Existing event semantics remain canonical, but client tool-call events gain the Toolkit source snapshot required by the summary contract defined below.

### Preserve event order after expansion

An expanded activity renders one ordered event stream. It does not regroup, merge, or reorder events by category.

Every presented event reuses its existing chat event component in transcript order, including that component's current summary and detail disclosure. The activity container does not introduce another phase or event-detail hierarchy.

Semantic categories are activity-summary metadata only. They never create phase sections in the expanded event list.

This decision supersedes [group-260720/ADR](./group-260720-group-chat-activity-in-the-frontend.md)'s three-level `Activity → phase → individual call` disclosure hierarchy. [group-260720/ADR](./group-260720-group-chat-activity-in-the-frontend.md) remains authoritative for frontend ownership, multi-turn activity continuity, and Generic fallback unless this ADR explicitly changes them.

### Treat attachment-bearing events as activity boundaries

Any event with one or more attachments renders outside Activity through its existing event component. The whole event remains outside rather than extracting or duplicating only its attachments.

An attachment-bearing event closes the preceding activity. Later internal work starts a new activity. This rule applies uniformly to message, client-tool, and provider-tool attachments without inferring whether a file is an operational artifact or a user-facing deliverable.

This decision supersedes [group-260720/ADR](./group-260720-group-chat-activity-in-the-frontend.md)'s selective promotion policy for validated deliverables.

### Keep user-facing control and result surfaces outside Activity

Activity owns internal work, not user-facing terminal results or standalone operations. Goal briefing, ActionExecution progress and results, run-level errors and retry controls, and user interruption notices render outside Activity through their existing components. Each closes the preceding Activity before it renders.

A failed, cancelled, or interrupted individual tool remains inside Activity at its chronological position and contributes an attention state to the collapsed row. Authorization remains a compact action on the latest open Activity when one exists; it falls back to its existing standalone surface when there is no open Activity.

This boundary keeps actionable controls and user-facing results discoverable without expanding Activity while preserving the internal event stream as one ordered process.

### Use the existing compact chat control pattern

The collapsed activity uses the same inline disclosure language as existing chat controls such as reasoning and turn-usage disclosure:

- one compact row;
- no outer bordered card, card background, or two-line block;
- a small chevron and icon;
- one fixed localized activity label followed by a dimmed work summary; and
- status or approval indicators only when they require attention.

The row remains collapsed by default. Expansion never occurs automatically because new events stream into the activity.

The summary renders complete category segments in first-occurrence order. When all categories do not fit, it replaces the hidden categories with a final localized overflow segment: `외 N` in Korean and `+N` in English. `N` counts hidden categories, not hidden events. Attention state reserves space before category fitting, and the activity control's accessible name retains the complete category list, counts, and state.

### Use a hybrid summary taxonomy

First-party and provider builtin tools use an explicit, frontend-owned intent taxonomy. Dynamically installed Toolkit tools use their Toolkit product name instead of per-tool intent classification.

Toolkit grouping is by product, not installation. Multiple GitHub installations therefore contribute one `GitHub` summary category; installation, repository, account, and target details belong to individual event summaries.

Categories are de-duplicated for the collapsed summary while preserving the order of their first occurrence. The expanded event stream always preserves every event and repetition.

The accepted category labels are:

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

Curated category labels are one word. English action categories use verbs. Product concepts, resource types, and fallback labels remain nouns. Toolkit product categories preserve their canonical display names and are not forced into the one-word convention.

`code_interpreter` and any other builtin that does not accurately belong to the accepted categories require explicit mapping validation before implementation; they must not be silently placed under `Shell`.

### Preserve Toolkit source identity in client tool-call events

A client tool call originating from a DB-attached Toolkit stores an immutable source snapshot with the call event. The snapshot contains:

- the source ToolkitConfig ID as the stable product-grouping key;
- the Toolkit type;
- the Toolkit display name at call time; and
- the Toolkit slug used by the execution catalog.

Builtin and auto-bound tools have no ToolkitConfig source snapshot and continue to use the explicit builtin taxonomy.

The engine obtains this identity from the exact `ToolCatalog` entry selected for execution. It must not reconstruct identity by parsing the model-visible tool name. Live and durable call projections expose the same snapshot, and the durable event remains sufficient after a Toolkit is renamed, detached, or deleted.

Client tool-call events created before this contract have no canonical Toolkit source. The revised Activity presentation still applies to those events. A pre-contract call uses the explicit builtin registry when its name is a known builtin; every other source-less call uses `Other`. The frontend does not infer legacy Toolkit identity or retain the previous Activity UI for historical events.

Installation, account, repository, and target identity are not part of the product-grouping key. Multiple installation-specific calls from one ToolkitConfig therefore contribute to one product category while retaining operation-specific context in their event summaries.

### Defer tool-specific detail designs

This revision defines the activity container, summary taxonomy, ordered event stream, and common event disclosure contract. Specialized detail designs for individual tools are a later design discussion. Until then, validated known tools may provide concise event summaries while Generic detail remains the compatibility fallback.

## Consequences

- Collapsed activity no longer competes visually with assistant communication.
- The summary communicates kinds of work rather than model-turn or tool-call counts.
- Reasoning and tool execution remain understandable as one chronological process.
- Builtin categories can be reviewed and localized deliberately, while new Toolkit tools require no per-tool frontend category registration.
- Client tool-call event and live projection contracts must carry the immutable Toolkit source snapshot when the call comes from a DB-attached Toolkit.
- The frontend projection must retain ordered heterogeneous activity events instead of storing tool calls and reasoning summaries in separate arrays.
- Existing phase-grouping code and phase-specific disclosure UI must be removed.
- Living conversation and Toolkit specs must be updated when the revised behavior is implemented.
- Compact-summary overflow remains deterministic without introducing a nested control.

## Alternatives Considered

### Keep reasoning outside tool activity

Rejected because it makes one internal work event follow different placement rules depending on neighboring tool calls and hides the causal order between reasoning and execution.

### Keep phase sections but preserve order inside each phase

Rejected because phase sections still reorder or visually separate events that occurred between calls of the same category.

### Classify every Toolkit tool by intent

Rejected because dynamic Toolkits would require continuous frontend taxonomy maintenance and unknown tools would receive inconsistent summaries.

### Group Toolkit tools by installation

Rejected because installation identity creates noisy duplicate categories in the collapsed row. Installation and target information remain available in each event summary and detail.

### Infer Toolkit ownership from tool names or current configuration

Rejected because a model-visible prefix is a routing namespace rather than a durable product contract. Name parsing cannot reliably cover unprefixed tools, renamed or deleted ToolkitConfigs, or historical transcript rendering.

## Migration provenance

- Historical source filename: `0174-present-chat-activity-as-an-ordered-event-stream.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
