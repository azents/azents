---
title: "Session Context Inspector"
tags: [chat, observability, event-events, frontend]
created: 2026-05-30
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, conversation]
last_verified_at: 2026-09-13
spec_version: 22
code_paths:
  - python/apps/azents/src/azents/services/agent/**
  - python/apps/azents/src/azents/api/public/agent/**
  - python/apps/azents/src/azents/services/chat/context.py
  - python/apps/azents/src/azents/api/public/chat/v1/__init__.py
  - python/apps/azents/src/azents/api/public/chat/v1/data.py
  - python/apps/azents/src/azents/repos/agent_execution/__init__.py
  - python/apps/azents/src/azents/repos/agent_session_system_prompt_snapshot/__init__.py
  - python/apps/azents/src/azents/rdb/models/agent_session_system_prompt_snapshot.py
  - python/apps/azents/src/azents/engine/events/types.py
  - python/apps/azents/src/azents/engine/events/execution.py
  - python/apps/azents/src/azents/engine/events/openai_responses.py
  - typescript/apps/azents-web/src/shared/agent-session/AgentSessionHeader.tsx
  - typescript/apps/azents-web/src/features/agents/AgentContextPage.tsx
  - typescript/apps/azents-web/src/features/chat/components/ChatSessionView.tsx
  - typescript/apps/azents-web/src/features/chat/components/TokenUsageIndicator.tsx
  - typescript/apps/azents-web/src/features/chat/containers/useChatSessionContainer.ts
  - typescript/apps/azents-web/src/shared/session-context/SessionContextView.tsx
---

# Session Context Inspector

## Current Behavior

Concrete Agent session screens keep Chat mounted as the main surface and expose
Context in a unified supporting panel. `?page=context`, `?page=system-prompt`,
and `?page=raw-events` select the existing inspector contents for the same
AgentSession without replacing Chat. The session header contains a panel toggle
rather than page-wide tabs. Desktop panel navigation is vertical; mobile
navigation is a horizontally scrollable tab row above full-width content, with
directional fades and scroll buttons. Existing inspector contents and detail
links remain unchanged. Unknown or absent page values render the normal session
surface; `?page=projects` redirects to that surface.

## Backend API

Public chat API provides this endpoint.

```http
GET /api/v1/chat/agents/{agent_id}/sessions/{session_id}/context?limit=300
```

Behavior:

1. Verify the AgentSession exists and belongs to the requested Agent.
2. Verify current user is a member of the session workspace.
3. Query recent events for that exact session within `limit`.
4. Query the selected session's current system prompt snapshot.
5. Use usage of most recent `turn_marker` event as latest usage.
6. Build event stats, approximate prompt-token breakdown, and raw events from events.

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
pricing-calculator `ValueError` leaves cost absent while preserving provider token usage. Unexpected
calculator defects remain visible through the ordinary internal-error path. ChatGPT OAuth cost is an
API-pricing estimate rather than subscription billing.

Chat tab header finds the most recent `turn_marker` usage from the loaded/live chat timeline and shows it in the token usage indicator. When clicked, the popup shows total, prompt, completion, cache read/write, and reasoning token counts. New markers also carry an immutable allowlisted snapshot of the exact Session inference state and applied candidate route: requested target label, raw nullable reasoning effort, operation kind, candidate ordinal and `primary | fallback` role, provider/integration/model identity, public model display name, effective context window, and effective automatic-compaction threshold. The popup renders this durable snapshot after terminal cleanup and reload. Historical markers without the snapshot or route remain valid; a matching active live Run may temporarily provide its applied profile, otherwise provenance and effective limits render as unavailable. Readers never substitute the current Session, Agent default, current candidate chain, or Composer selection.

## Latest System Prompt

The Context inspector stores one replaceable `SystemPromptAnalysisPayload` per AgentSession.
Successful model-output admission updates that snapshot in the same transaction as the model
output and usage turn marker. A successful model call with no assembled system prompt deletes
the existing snapshot so the inspector cannot report stale prompt data.

Turn markers do not store system prompt analysis. The inspector reads the session snapshot
directly and does not fall back to historical event payloads.

The storage migration copies the latest legacy prompt payload per session into the snapshot,
then removes `system_prompt` from legacy turn-marker JSON. PostgreSQL autovacuum can reuse the
resulting dead event-row space; reducing the physical `events` table file immediately requires
an operator-scheduled table rewrite such as `VACUUM FULL` or `pg_repack`.

## Approximate Breakdown

Prompt breakdown is not exact tokenizer result and does not estimate token count. Backend does not use provider `prompt_tokens` as breakdown total. Instead, it sums character counts of prompt components whose source is known and calculates ratio within that total character count.

Categories:

- `system`: final system prompt from the current session snapshot. If final prompt is absent, sum character counts of agent/toolkit/injected prompt fragments.
- `user`: `UserMessagePayload.content`
- `assistant`: `AssistantMessagePayload.content` and `ReasoningPayload`
- `tool`: client tool call arguments/result text plus the deterministic provider-call semantic transcript, including input, textual output, typed references, and bounded canonical output-part metadata
- `other`: not shown in normal case because only prompt components with known source are calculated

Frontend explains that breakdown is character-count based. Input token count itself is displayed as provider usage value in Usage summary.

## Raw Events

Context response provides recent events as raw JSON. Frontend renders them as accordion and lets user inspect kind, timestamp, model, and payload of each event.

Raw events are exposed only to workspace members. Endpoint applies event limit to constrain response size.

## Frontend

`/w/{handle}/agents/{agentId}/sessions/{sessionId}?page=context` renders these states in the session supporting panel:

- loading
- error
- empty selected session transcript
- ready

Ready state includes this UI:

- token summary cards
- prompt character breakdown bar
- event stats cards
- links to `?page=system-prompt` and `?page=raw-events` detail views

`?page=system-prompt` renders system prompt fragments. `?page=raw-events` renders
the raw event JSON accordion. Both retain the same Chat mount and session.

## Verification

As of 2026-07-21, verified through model-output admission, Context snapshot projection, and turn-marker
serialization checks. Version 18 retains one replaceable prompt diagnostic snapshot per session instead of
repeated prompt bodies in transcript turn markers, while preserving turn usage provenance and provider-tool
semantic transcript breakdown.

```bash
cd python/apps/azents && uv run ruff check src/azents/services/chat/context.py
cd python/apps/azents && uv run pyright src/azents/services/chat/context.py src/azents/api/public/chat/v1/data.py src/azents/api/public/chat/v1/__init__.py src/azents/repos/agent_execution/__init__.py
cd typescript && corepack pnpm --filter @azents/web format:check
cd typescript && corepack pnpm --filter @azents/web typecheck
```

## Changelog

- **2026-09-13** — v22. Added immutable actual-candidate route details, including candidate role
  and ordinal, without deriving historical provenance from current Agent configuration.
- **2026-09-12** — v21. Embedded the unchanged Context inspector in the unified
  session panel while keeping Chat mounted.

- **2026-09-06** — v20. Distinguished absent or invalid public-pricing estimates
  from unexpected calculator defects that remain visible to monitoring.
- **2026-09-04** — v19. Updated the Session Context view mapping after its
  behavior-preserving move to the shared frontend layer.
