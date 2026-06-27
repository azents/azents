---
title: "Session Context Inspector"
tags: [chat, observability, event-events, frontend]
created: 2026-05-30
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation]
last_verified_at: 2026-06-27
spec_version: 9
code_paths:
  - python/apps/azents/src/azents/services/agent/**
  - python/apps/azents/src/azents/api/public/agent/**
  - python/apps/azents/src/azents/services/chat/context.py
  - python/apps/azents/src/azents/api/public/chat/v1/__init__.py
  - python/apps/azents/src/azents/api/public/chat/v1/data.py
  - python/apps/azents/src/azents/repos/agent_execution/__init__.py
  - typescript/apps/azents-web/src/features/agents/components/AgentSessionHeader.tsx
  - typescript/apps/azents-web/src/features/agents/AgentContextPage.tsx
  - typescript/apps/azents-web/src/features/chat/components/ChatSessionView.tsx
  - typescript/apps/azents-web/src/features/chat/components/TokenUsageIndicator.tsx
  - typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts
  - typescript/apps/azents-web/src/features/chat/context/SessionContextView.tsx
---

# Session Context Inspector

## Current Behavior

Concrete Agent session screens provide `Chat`, `Projects`, and `Context` header tabs. `Context` is selected by the session URL query `?page=context`; it shows model context usage and event source based on the URL-selected AgentSession. `?page=system-prompt` and `?page=raw-events` expose detail views for the same selected session. These tabs are session-scoped and are not rendered on the independent Agent settings page. These query-param routes preserve the same page layout as the former dedicated Context pages: session header, tab navigation, and a scrollable inspector content area.

## Backend API

Public chat API provides this endpoint.

```http
GET /api/v1/chat/agents/{agent_id}/sessions/{session_id}/context?limit=300
```

Behavior:

1. Verify the AgentSession exists and belongs to the requested Agent.
2. Verify current user is a member of the session workspace.
3. Query recent events for that exact session within `limit`.
4. Use usage of most recent `turn_marker` event as latest usage.
5. Build event stats, approximate prompt-token breakdown, and raw events from events.

`limit` minimum is 1, maximum is 500. Default is 300.

## Empty Transcript

Context query is read-only and requires an existing `session_id`. It does not create or fall back to a team-primary session. When the selected session has no context events, response `session.id` remains the selected session id, `usage` is `null`, and stats/breakdown/raw events are empty.

## Usage Summary

Latest usage comes from event `TurnMarkerPayload.usage`. Usage is value returned by provider/adapter and can include:

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `cached_tokens`
- `cache_creation_tokens`
- `reasoning_tokens`
- `cost_usd`
- raw provider usage payload

Chat tab header finds most recent `turn_marker` usage from loaded/live chat timeline and shows it as token usage indicator. Indicator compares latest `total_tokens` with `effective_auto_compaction_threshold_tokens` in Agent response and shows auto compaction threshold usage as small donut. When clicked, popup shows total, prompt, completion, cache read/write, reasoning, effective context window, and auto compaction threshold as numbers. Effective context window is `effective_context_window_tokens` in Agent response, calculated by backend with same criterion as runtime auto compaction trigger: `min(main_model_max_input, effective_lightweight_model_max_input)`. Effective lightweight is interpreted from `lightweight_model_selection` snapshot stored in Agent. Workspace default is copied only at Agent create/update time and is not looked up again in context inspector/runtime calculation. Subagent also uses its own model snapshot and has no parent model runtime inheritance. If effective values are absent, usage numbers are shown but model/context/threshold are shown as unavailable.

## Approximate Breakdown

Prompt breakdown is not exact tokenizer result and does not estimate token count. Backend does not use provider `prompt_tokens` as breakdown total. Instead, it sums character counts of prompt components whose source is known and calculates ratio within that total character count.

Categories:

- `system`: final system prompt stored in latest `TurnMarkerPayload.system_prompt`. If final prompt is absent, sum character counts of agent/toolkit/injected prompt fragments.
- `user`: `UserMessagePayload.content`
- `assistant`: `AssistantMessagePayload.content` and `ReasoningPayload`
- `tool`: client/provider tool call arguments and tool result output text
- `other`: not shown in normal case because only prompt components with known source are calculated

Frontend explains that breakdown is character-count based. Input token count itself is displayed as provider usage value in Usage summary.

## Raw Events

Context response provides recent events as raw JSON. Frontend renders them as accordion and lets user inspect kind, timestamp, model, and payload of each event.

Raw events are exposed only to workspace members. Endpoint applies event limit to constrain response size.

## Frontend

`/w/{handle}/agents/{agentId}/sessions/{sessionId}?page=context` renders these states in the Context page layout:

- loading
- error
- empty selected session transcript
- ready

Ready state includes this UI:

- token summary cards
- prompt character breakdown bar
- event stats cards
- links to `?page=system-prompt` and `?page=raw-events` detail views

`?page=system-prompt` renders system prompt fragments. `?page=raw-events` renders raw event JSON accordion. Unknown or absent `page` values render the normal chat view.

## Verification

As of 2026-05-30, verified with these checks.

```bash
cd python/apps/azents && uv run ruff check src/azents/services/chat/context.py
cd python/apps/azents && uv run pyright src/azents/services/chat/context.py src/azents/api/public/chat/v1/data.py src/azents/api/public/chat/v1/__init__.py src/azents/repos/agent_execution/__init__.py
cd typescript && corepack pnpm --filter @azents/web format:check
cd typescript && corepack pnpm --filter @azents/web typecheck
```
