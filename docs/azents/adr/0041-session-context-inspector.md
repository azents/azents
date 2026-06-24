---
title: "ADR-0041: Session Context Inspector"
tags: [chat, observability, canonical-events, frontend]
created: 2026-05-30
---

# ADR-0041: Session Context Inspector

## Context

Azents stores agent execution as canonical events and already records per-turn model usage in `turn_marker` events. The chat UI currently exposes token usage only inline at turn boundaries. This makes it hard to diagnose context bloat, oversized tool outputs, unexpected compaction pressure, or projection bugs because there is no single place to inspect the current session context and the raw canonical events behind the rendered chat.

OpenCode exposes a session context view with usage stats, approximate token breakdown, system prompt visibility, and raw message inspection. Azents needs an equivalent inspector that fits its canonical transcript architecture.

## Decision

Add a top-level **Context** tab to the Agent detail page, next to **Chat** and **Settings**. The tab will inspect the Agent's active session and show:

- latest turn usage summary;
- aggregate canonical event stats;
- approximate prompt-token breakdown by source category;
- raw canonical event JSON.

The MVP will use existing canonical transcript data and `turn_marker` usage. It will not introduce a new persistence layer for native model requests or raw provider stream events. Any breakdown finer than provider-reported usage will be explicitly approximate.

## Considered options

### Option A — Add a Context top-level Agent tab

The inspector is available as a peer to Chat and Settings.

Pros:

- Matches the requested placement.
- Makes context inspection discoverable.
- Keeps debugging information out of the main chat timeline.

Cons:

- Requires an additional route and active-session lookup.
- Does not naturally inspect historical sessions unless a session-specific route is added later.

### Option B — Add a Workspace panel sub-tab

The inspector appears inside the existing right-side workspace panel.

Pros:

- Reuses existing panel layout.
- Keeps the chat route unchanged.

Cons:

- Confuses context inspection with workspace/project browsing.
- Does not match the requested Chat/Settings tab location.
- The panel can be closed or hidden on smaller layouts.

### Option C — Add a turn-level modal or drawer

The user opens context details from a specific turn divider.

Pros:

- Natural for turn-specific usage.
- Requires less top-level navigation.

Cons:

- Lower discoverability for session-wide debugging.
- Raw event browsing becomes awkward.
- Does not support a persistent context diagnostics page.

## Consequences

- The initial inspector is scoped to the active session for an Agent.
- Historical-session context inspection requires future routing or session selection work.
- Prompt breakdown is approximate until Azents persists model-input snapshots or introduces tokenizer-backed accounting.
- Raw canonical events become user-visible to authorized workspace members, so access control and response size limits are required.
- Future native request/raw stream inspection should be designed as an explicit debug artifact, not mixed into the canonical event stream by default.
