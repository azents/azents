---
title: "ADR-0174: Present Chat Activity as an Ordered Event Stream"
created: 2026-07-20
tags: [architecture, frontend, chat, tools, ux]
---

# ADR-0174: Present Chat Activity as an Ordered Event Stream

## Context

ADR-0173 moved continuous chat tool work into a frontend-owned `Activity` presentation, but the implemented presentation introduced three problems:

1. the collapsed activity uses a large bordered card that visually dominates the conversation;
2. its summary exposes implementation counts such as model turns and tool calls instead of the kinds of work performed; and
3. expansion regroups calls into semantic phases, separating reasoning from tools and destroying the original event order.

Reasoning and other internal work events are also projected inconsistently: an event may appear inside or outside an activity depending on whether a tool group already exists. The product requires one predictable rule for all internal work events.

The activity summary must support first-party builtins without hard-coding every dynamically installed Toolkit tool. Toolkit products may also have multiple installations, but installation identity is detail rather than top-level activity-summary information.

## Decision

### Treat Activity as a continuous internal-work stream

The frontend activity projection starts from the first internal work event, not from the first tool call. All internal work events between user-visible delivery boundaries belong to the activity regardless of event type. This includes reasoning, Skill use, client and provider tool calls, compaction, and other internal control events that receive chat presentation.

Reasoning does not render as a separate Thinking block when it belongs to an activity. A reasoning-only work period can create an activity without any tool call.

User-visible messages and deliverables remain outside activity and separate adjacent work periods. Backend event, API, durable transcript, and live-state payloads remain unchanged.

### Preserve event order after expansion

An expanded activity renders one ordered event stream. It does not regroup, merge, or reorder events by category.

Every presented event has:

- a compact summary row in transcript order; and
- independently expandable detail for the information owned by that event.

Semantic categories are activity-summary metadata only. They never create phase sections in the expanded event list.

This decision supersedes ADR-0173's three-level `Activity → phase → individual call` disclosure hierarchy. ADR-0173 remains authoritative for frontend ownership, multi-turn activity continuity, Generic fallback, and promoted user-facing deliverables unless this ADR explicitly changes them.

### Use the existing compact chat control pattern

The collapsed activity uses the same inline disclosure language as existing chat controls such as reasoning and turn-usage disclosure:

- one compact row;
- no outer bordered card, card background, or two-line block;
- a small chevron and icon;
- one fixed localized activity label followed by a dimmed work summary; and
- status or approval indicators only when they require attention.

The row remains collapsed by default. Expansion never occurs automatically because new events stream into the activity.

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

Category names are one word. English action categories use verbs. Product concepts, resource types, fallback, and Toolkit proper names remain nouns.

`code_interpreter` and any other builtin that does not accurately belong to the accepted categories require explicit mapping validation before implementation; they must not be silently placed under `Shell`.

### Defer tool-specific detail designs

This revision defines the activity container, summary taxonomy, ordered event stream, and common event disclosure contract. Specialized detail designs for individual tools are a later design discussion. Until then, validated known tools may provide concise event summaries while Generic detail remains the compatibility fallback.

## Consequences

- Collapsed activity no longer competes visually with assistant communication.
- The summary communicates kinds of work rather than model-turn or tool-call counts.
- Reasoning and tool execution remain understandable as one chronological process.
- Builtin categories can be reviewed and localized deliberately, while new Toolkit tools require no per-tool frontend category registration.
- The frontend projection must retain ordered heterogeneous activity events instead of storing tool calls and reasoning summaries in separate arrays.
- Existing phase-grouping code and phase-specific disclosure UI must be removed.
- Living conversation specs must be updated when the revised behavior is implemented.
- The compact summary overflow policy remains an open design decision and is not decided by this ADR.

## Alternatives Considered

### Keep reasoning outside tool activity

Rejected because it makes one internal work event follow different placement rules depending on neighboring tool calls and hides the causal order between reasoning and execution.

### Keep phase sections but preserve order inside each phase

Rejected because phase sections still reorder or visually separate events that occurred between calls of the same category.

### Classify every Toolkit tool by intent

Rejected because dynamic Toolkits would require continuous frontend taxonomy maintenance and unknown tools would receive inconsistent summaries.

### Group Toolkit tools by installation

Rejected because installation identity creates noisy duplicate categories in the collapsed row. Installation and target information remain available in each event summary and detail.
