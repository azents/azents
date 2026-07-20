---
title: "ADR-0173: Group Chat Tool Activity in the Frontend"
created: 2026-07-20
tags: [architecture, frontend, chat, tools, ux]
---

# ADR-0173: Group Chat Tool Activity in the Frontend

## Context

Azents currently projects client and provider tool calls into individual chat cards. This preserves diagnostic detail, but a long-running Agent may produce many cards across several model turns before it sends another user-visible response. The repeated cards, status badges, arguments, outputs, and attachments dominate the timeline and make the assistant's actual communication harder to scan.

The canonical event and frontend projection models already expose stable tool identity, name, status, arguments, output, and attachments through `call_id`, `ActiveToolCall`, and `ProviderToolCall`. Changing backend tool payloads solely to support a calmer presentation would couple the event contract to one UI composition and duplicate information that the frontend already has.

The product requires multi-turn grouping when tool execution continues without visible assistant communication, progressive disclosure for details, specialized presentation only for payload shapes the frontend understands, and a safe generic fallback for every other shape.

## Decision

### Keep tool activity composition frontend-owned

Chat tool grouping, phase summaries, expansion state, and renderer selection are frontend presentation concerns. The backend event, API, live-state, and durable transcript shapes remain unchanged.

The frontend converts the already ordered chat timeline into presentation atoms and then groups adjacent tool-call atoms. It preserves the existing `call_id`-based live-to-durable identity and does not introduce a persisted activity-group identifier.

### Group across model turns until a user-visible boundary

A tool activity group continues across model-turn markers, reasoning, compaction, retries, tool-only messages, and permission pause or resume when no explicit user-visible delivery intervenes.

The current group ends at:

- a user message;
- visible assistant text;
- an assistant-level attachment or artifact;
- a known tool result promoted by the frontend as an explicit user-facing deliverable;
- a new Run after the previous Run has terminated; or
- an explicit task or subagent transition.

A user-facing delivery is rendered outside the preceding activity group. If tool execution continues after that delivery, the next tool call starts a new group.

### Use a fixed group title and progressive disclosure

Every group uses the localized fixed title `Activity`. The title is not generated from tool names or outputs and does not change while work streams.

The group has three presentation levels:

1. a collapsed one-row group summary by default;
2. ordered phase summaries after the group is expanded; and
3. individual specialized or generic tool details after a phase is expanded.

Failure counts and pending approval actions remain visible while the group is collapsed. Streaming updates never force a group open.

### Specialize only validated known payloads

A frontend registry may select a specialized renderer only when:

- the tool identity is registered;
- the available argument shape validates against the registered schema;
- the available output shape validates against the registered schema; and
- adapter conversion succeeds.

A running call may omit output when its adapter explicitly permits that state. Unknown tools, unknown payload variants, malformed payloads, validation failures, and adapter errors use the Generic Tool Call renderer.

Generic rendering is the permanent compatibility boundary. It must preserve status, raw arguments, raw output, and attachments without inferring semantic meaning.

### Promote only known user-facing deliverables

Assistant-level attachments and artifacts remain explicit user-visible output. A specialized tool adapter may also identify a validated image or file result as a user-facing deliverable. Those results render outside the activity group and create a group boundary.

Unknown or operational attachments remain inside generic or specialized tool details, with only a count shown in collapsed summaries. Promoted deliverables are not rendered a second time inside tool details.

## Consequences

- Long tool-only sequences occupy one collapsed timeline row by default, even when they span several model turns.
- Users can progressively inspect phases and individual calls without losing raw diagnostic access.
- The backend and public event contracts do not acquire UI-specific grouping or semantic-summary fields.
- New or changed tools remain renderable through the Generic Tool Call fallback before a specialized adapter exists.
- Specialized summaries are deterministic and limited to validated frontend-owned schemas.
- User-visible images and files remain immediately discoverable instead of being hidden behind a collapsed execution group.
- The frontend timeline renderer must move from message-by-message tool-card composition to an ordered presentation projection that also respects action-execution placement and invisible boundary markers.
- The implementation must update the conversation and attachment presentation specs because current behavior renders tool-generated attachments inside individual tool cards.

## Alternatives Considered

### Add backend activity-group and phase-summary payloads

Rejected because grouping and progressive disclosure are presentation policy. Existing tool events already contain the identity and payload needed by the frontend, and backend summaries would create a new compatibility contract for one UI.

### Render every tool call as an individual collapsed card

Rejected because the number of visible rows still grows linearly with tool calls and continues to dominate long Agent runs.

### Expand a group directly to individual tool calls

Rejected because one click would restore most of the original visual noise. Ordered phase summaries provide a useful intermediate level.

### Generate a dynamic group title

Rejected because mixed tool activity has no reliable single semantic title, titles would change while streaming, and generic payloads could not produce equally trustworthy titles.

### Hide every attachment inside the activity group

Rejected because Agent-produced images and deliverable files are explicit communication that users should not have to discover through diagnostic expansion.

### Promote every tool attachment outside the group

Rejected because logs, intermediate files, and unknown attachments would recreate the timeline noise the grouping design is intended to remove.
