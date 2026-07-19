---
title: "Session Context Inspector"
tags: [chat, observability, event-events, frontend]
created: 2026-05-30
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation]
last_verified_at: 2026-07-18
spec_version: 16
code_paths:
  - python/apps/azents/src/azents/services/agent/**
  - python/apps/azents/src/azents/api/public/agent/**
  - python/apps/azents/src/azents/services/chat/context.py
  - python/apps/azents/src/azents/api/public/chat/v1/__init__.py
  - python/apps/azents/src/azents/api/public/chat/v1/data.py
  - python/apps/azents/src/azents/repos/agent_execution/__init__.py
  - python/apps/azents/src/azents/engine/events/types.py
  - python/apps/azents/src/azents/engine/events/execution.py
  - python/apps/azents/src/azents/engine/events/openai_responses.py
  - typescript/apps/azents-web/src/features/agents/components/AgentSessionHeader.tsx
  - typescript/apps/azents-web/src/features/agents/AgentContextPage.tsx
  - typescript/apps/azents-web/src/features/chat/components/ChatSessionView.tsx
  - typescript/apps/azents-web/src/features/chat/components/TokenUsageIndicator.tsx
  - typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts
  - typescript/apps/azents-web/src/features/chat/context/SessionContextView.tsx
---

# Session Context Inspector

## Current Behavior

Concrete Agent session screens provide `Chat` and `Context` header tabs. Project management is part of the Workspace surface, not a separate session header tab. `Context` is selected by the session URL query `?page=context`; it shows model context usage and event source based on the URL-selected AgentSession. `?page=system-prompt` and `?page=raw-events` expose detail views for the same selected session. These tabs are session-scoped and are not rendered on the independent Agent settings page. These query-param routes preserve the same page layout as the former dedicated Context pages: session header, tab navigation, and a scrollable inspector content area. Unknown or legacy page values, including `?page=projects`, render the normal chat/session surface.

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

For OpenAI API-key and ChatGPT OAuth turns, token fields and raw usage come directly from the official
OpenAI SDK completed `ResponseUsage`; raw usage does not contain synthetic LiteLLM hidden parameters.
Their `cost_usd` is a content-free LiteLLM public price-map estimate. Unsupported pricing or a
calculator failure leaves cost absent while preserving provider token usage. ChatGPT OAuth cost is an
API-pricing estimate rather than subscription billing.

Chat tab header finds the most recent `turn_marker` usage from the loaded/live chat timeline and shows it in the token usage indicator. When clicked, the popup shows total, prompt, completion, cache read/write, and reasoning token counts. New markers also carry an immutable allowlisted snapshot of the exact Session inference state applied to that model call: target label, raw nullable reasoning effort, nullable model display name, effective context window, and effective automatic-compaction threshold. The popup renders this durable snapshot after terminal cleanup and reload. Historical markers without the snapshot remain valid; a matching active live Run may temporarily provide its applied profile, otherwise provenance and effective limits render as unavailable. Readers never substitute the current Session, Agent default, or Composer selection.

## Approximate Breakdown

Prompt breakdown is not exact tokenizer result and does not estimate token count. Backend does not use provider `prompt_tokens` as breakdown total. Instead, it sums character counts of prompt components whose source is known and calculates ratio within that total character count.

Categories:

- `system`: final system prompt stored in latest `TurnMarkerPayload.system_prompt`. If final prompt is absent, sum character counts of agent/toolkit/injected prompt fragments.
- `user`: `UserMessagePayload.content`
- `assistant`: `AssistantMessagePayload.content` and `ReasoningPayload`
- `tool`: client tool call arguments/result text plus the deterministic provider-tool semantic transcript from both call and result events, including input, textual output, and typed references
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

`?page=system-prompt` renders system prompt fragments. `?page=raw-events` renders raw event JSON accordion. Unknown, legacy, or absent `page` values render the normal chat view.

## Verification

As of 2026-07-18, verified through the chat Run state checks, context inspector checks, official
OpenAI SDK usage-normalization coverage, and provider-tool semantic transcript breakdown tests.
Version 16 measures provider-tool call and result events through the same deterministic semantic
renderer used by model-visible consumers while retaining SDK usage provenance, immutable per-turn
profile and effective-limit snapshots, and unsynthesized unavailable historical fields.

```bash
cd python/apps/azents && uv run ruff check src/azents/services/chat/context.py
cd python/apps/azents && uv run pyright src/azents/services/chat/context.py src/azents/api/public/chat/v1/data.py src/azents/api/public/chat/v1/__init__.py src/azents/repos/agent_execution/__init__.py
cd typescript && corepack pnpm --filter @azents/web format:check
cd typescript && corepack pnpm --filter @azents/web typecheck
```
