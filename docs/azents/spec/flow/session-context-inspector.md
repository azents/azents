---
title: "Session Context Inspector"
tags: [chat, observability, event-events, frontend]
created: 2026-05-30
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation]
last_verified_at: 2026-06-16
spec_version: 5
code_paths:
  - python/apps/azents/src/azents/services/agent/**
  - python/apps/azents/src/azents/api/public/agent/**
  - python/apps/azents/src/azents/services/chat/context.py
  - python/apps/azents/src/azents/api/public/chat/v1/__init__.py
  - python/apps/azents/src/azents/api/public/chat/v1/data.py
  - python/apps/azents/src/azents/repos/agent_execution/__init__.py
  - typescript/apps/azents-web/src/features/agents/components/AgentHeader.tsx
  - typescript/apps/azents-web/src/features/agents/AgentContextTabPage.tsx
  - typescript/apps/azents-web/src/features/chat/components/ChatSessionView.tsx
  - typescript/apps/azents-web/src/features/chat/components/TokenUsageIndicator.tsx
  - typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts
  - typescript/apps/azents-web/src/features/chat/context/SessionContextView.tsx
---

# Session Context Inspector

## Current Behavior

Agent detail screen provides `Chat`, `Context`, and `Settings` top-level tabs. `Context` tab is an inspector that shows model context usage and event source based on the Agent's currently open session row.

## Backend API

Public chat API provides this endpoint.

```http
GET /api/v1/chat/agents/{agent_id}/context?limit=300
```

Behavior:

1. Verify Agent exists.
2. Verify current user is Agent workspace member.
3. Look up the Agent's active session row without using AgentRuntime session-selection state.
4. If an active session does not exist, return empty context payload.
5. If an active session exists, query recent events within `limit`.
6. Use usage of most recent `turn_marker` event as latest usage.
7. Build event stats, approximate prompt-token breakdown, and raw events from events.

`limit` minimum is 1, maximum is 500. Default is 300.

## Empty Session

Context query is read-only. It does not create a new session when an active session does not exist. In this case, response `session.id` is `null`, `usage` is `null`, and stats/breakdown/raw events are empty.

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

`/w/{handle}/agents/{agentId}/context` route renders these states:

- loading
- error
- empty active session
- ready

Ready state includes this UI:

- token summary cards
- prompt character breakdown bar
- event stats cards
- raw event JSON accordion

## Verification

As of 2026-05-30, verified with these checks.

```bash
cd python/apps/azents && uv run ruff check src/azents/services/chat/context.py
cd python/apps/azents && uv run pyright src/azents/services/chat/context.py src/azents/api/public/chat/v1/data.py src/azents/api/public/chat/v1/__init__.py src/azents/repos/agent_execution/__init__.py
cd typescript && corepack pnpm --filter @azents/web format:check
cd typescript && corepack pnpm --filter @azents/web typecheck
```
