---
title: "Chat Activity Ordered Event Revision"
created: 2026-07-20
updated: 2026-07-20
tags: [frontend, chat, tools, ux, testing]
---

# Chat Activity Ordered Event Revision

## Problem

The first Chat Tool Activity implementation reduced the number of timeline items, but its visual and information architecture do not meet the product goal:

- the collapsed activity is a large bordered card rather than a calm inline disclosure;
- the summary reports model-turn and tool-call counts instead of the kinds of work performed;
- reasoning may render outside the activity while tools render inside it;
- expansion regroups events into phases and loses the chronological relationship among reasoning, Skill use, tools, and internal control events; and
- known-tool specialization was reduced to phase labels while raw detail cards remained largely generic.

This revision follows [ADR-0174](../adr/0174-present-chat-activity-as-an-ordered-event-stream.md). It preserves ADR-0173's frontend-owned grouping and backend compatibility boundary while replacing its phase hierarchy.

## Goals

- Make the collapsed activity visually consistent with existing compact chat disclosures.
- Apply one grouping rule to every internal work event.
- Preserve exact event order across reasoning, tools, model turns, compaction, and other internal work.
- Summarize the kinds of work performed instead of implementation counts.
- Classify builtins by reviewed product intent and dynamic Toolkit tools by Toolkit product.
- Keep each event independently inspectable.
- Preserve Generic detail as the compatibility fallback.

## Non-goals

- Changing backend event, API, durable transcript, or live-state payloads.
- Designing every known tool's specialized detail surface in this revision.
- Inferring Toolkit ownership from arbitrary tool-name prefixes.
- Showing Toolkit installation identity in the collapsed activity summary.
- Deciding the compact-summary overflow treatment before product-case research and user approval.

## Accepted Decisions

### Compact activity control

The collapsed activity uses the shared inline chat-control visual language instead of a `Paper` card. It is one row with a small disclosure chevron, activity icon, fixed activity label, dimmed category summary, and attention state when needed.

The collapsed row removes model-turn and tool-call counts. It does not use a border, card background, large radius, or two-line title/metadata layout.

### Consistent event ownership

Every internal work event between user-visible delivery boundaries belongs to the activity. The activity may begin with reasoning or Skill use and may exist without a tool call.

Reasoning, Skill use, tools, compaction, and other internal work events do not alternate between standalone and grouped presentation based on neighboring event types.

### Ordered expansion

The expanded activity renders `ActivityEvent[]` in transcript order. Each event owns a compact summary and independently expandable detail. No phase headings, phase aggregation, category sorting, or event de-duplication occur inside expansion.

Category de-duplication applies only to the collapsed summary.

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

English action categories use one-word verbs. Product concepts, resource types, fallback, and Toolkit proper names use one-word nouns.

### Tool-specific detail design sequencing

The common ordered event row and disclosure behavior are designed and implemented first. Tool-specific detail presentations are discussed only after this revision is validated. This deferral does not remove tool-specific presentation from the product roadmap.

## Required Projection Changes

The current presentation model separates `calls` from `reasoningSummaries`, which cannot reconstruct their interleaving. Replace that structure with one ordered heterogeneous event sequence.

The target conceptual projection is:

```text
ActivityGroup
  id
  start/end timeline position
  ordered events
  collapsed category summary
  attention state

ActivityEvent
  reasoning | tool | skill | compaction | other internal event
  stable source identity
  compact summary
  expandable detail ownership
  optional category
  status
```

This is a frontend projection only. Existing event and tool payloads remain canonical.

## Open Decisions

### Collapsed-summary overflow

The summary may contain more categories than fit in a mobile row. The treatment is not yet selected. Candidate approaches must be compared against real product examples and rendered with the production component before approval.

Questions:

- Should lower-priority categories truncate visually, collapse into a count, or move into an accessible overflow affordance?
- Should first-occurrence order determine which categories remain visible?
- Must attention states such as failure and approval displace category labels?
- How should the full category list remain available to screen readers and pointer users?

### Remaining builtin mapping

Validate every actual builtin against the accepted categories. `code_interpreter` must not be assigned to `Shell` merely because both execute code. Any builtin without an accurate accepted category remains `Other` until its mapping is approved.

### Event summary names

Reasoning, compaction, authorization, and each common builtin need concise event-row summaries. These names are separate from activity category labels and remain to be reviewed.

## Test Strategy

### Primary E2E verification

Use deterministic Main Web E2E coverage with a transcript containing:

1. reasoning before the first tool;
2. Skill use;
3. alternating reasoning and builtin calls across multiple model turns;
4. Toolkit calls from multiple installations of one product;
5. compaction or another internal control event;
6. a visible assistant delivery boundary; and
7. later internal work that starts a new activity.

Verify that all internal events before the delivery appear in one activity in exact order, the delivery remains outside, and later work starts a separate activity. Refresh must preserve the same projection.

### Frontend projection tests

- reasoning-only work creates an activity;
- reasoning before, between, and after tools remains ordered inside the activity;
- category calculation does not reorder events;
- repeated categories de-duplicate only in the collapsed summary;
- multiple Toolkit installations contribute one product category;
- unknown builtins use `Other`;
- visible deliveries create boundaries consistently;
- live-to-durable replacement preserves event identity and order.

### Component and visual verification

Render the real component through Storybook or the app surface under production providers and fonts.

Required states:

- collapsed and expanded;
- short and overflowing category summaries;
- reasoning-only activity;
- mixed builtin and Toolkit activity;
- running, failed, and approval-required states;
- desktop and narrow mobile;
- light and dark themes.

Compare the collapsed row against existing inline chat disclosures for height, typography, chevron placement, spacing, and visual weight. Capture native-resolution screenshots and confirm no horizontal overflow.

### Accessibility verification

- the activity row exposes expanded state and a complete accessible summary;
- every event disclosure is independently keyboard operable;
- DOM order matches transcript order;
- truncation does not remove category information from the accessible name;
- attention states remain announced without forcing expansion.

### CI policy

Run web lint, typecheck, unit tests, Storybook build, deterministic browser checks, and the required web-surface E2E job. Docker-dependent full-stack validation may be delegated to CI when unavailable locally, but no local full-stack pass may be claimed in that case.
