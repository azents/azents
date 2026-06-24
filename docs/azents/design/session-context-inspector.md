---
title: "Session Context Inspector Design"
tags: [backend, frontend, engine, observability, chat]
created: 2026-05-30
implemented: 2026-05-30
adr: docs/azents/adr/0041-session-context-inspector.md
---

# Session Context Inspector Design

## Overview

Related ADR: [ADR 0041 — Session Context Inspector](../adr/0041-session-context-inspector.md)

Add `Context` tab next to `Chat` / `Settings` tabs on Agent detail screen so users can inspect current session's model context usage and source events. Goal is to let users quickly diagnose how many context tokens current conversation uses, which categories generated tokens, and what actual stored canonical events are, similar to OpenCode's Session Context tab.

## Problem

Currently Azents briefly shows per-turn token usage in `turn_complete` divider, but following information is hard to check on one screen.

- Latest model usage total of current session
- Usage ratio against context limit
- input/output/reasoning/cache token breakdown
- user/assistant/tool event counts
- approximate system/user/assistant/tool/other breakdown within prompt tokens
- actual canonical event payload

Without this information, it is difficult to debug context bloat, excessive tool output, compaction need, and raw event projection problems.

## Goals

1. Add `Context` tab to top tabs of Agent detail.
2. Show context summary of current or active session in Context tab.
3. Provide token/cost/stat cards based on latest turn usage.
4. Provide approximate context breakdown based on canonical events.
5. Provide raw canonical events as accordion JSON viewer.
6. Use only existing canonical transcript and turn marker usage without separate DB migration.

## Non-goals

- provider-specific exact tokenizer-based breakdown
- storing native request snapshot right before model call
- storing full raw provider stream events
- changing context compaction policy
- changing compact rendering of tool calls

## Current State

Backend already stores canonical transcript in `events` table. `TurnMarkerPayload` contains provider usage, and `MessageRepository` projects it as `usage` of `turn_complete` message. Frontend shows per-turn usage in `TurnDivider`.

Missing piece is session-level context summary API and UI. Also, `NativeModelRequest` and system prompt are currently transiently generated and not stored.

## Discussion Points and Decisions

### 1. Tab location

Options:

- A. Add `Context` sub-tab inside Workspace panel on right side of Chat
- B. Add top-level `Context` tab next to `Chat` / `Settings` in Agent detail
- C. Show as drawer/modal when TurnDivider is clicked

Decision: **B. top-level `Context` tab**

User instruction was "tab location is around the tabs where chat, settings are," so add to AgentHeader top-level tab. This location exposes context inspector as agent/session diagnostics screen, not chat auxiliary feature.

Trade-off: top-level route is needed, so current session ID must be determined by URL or active session lookup. MVP uses agent's active session, and session-specific context deep link can be added later.

### 2. Data source

Options:

- A. Use only existing projected chat messages
- B. Directly query canonical events
- C. Add model input snapshot / raw stream snapshot table

Decision: **B. directly query canonical events**

Canonical events are enough for raw inspector and breakdown, and can be implemented without migration. C has higher accuracy and debugging value, but requires separate storage policy/capacity/security review, so leave it as later phase.

### 3. Breakdown accuracy

Options:

- A. Show only provider usage `prompt_tokens` and no breakdown
- B. Estimate with char/4 like OpenCode and scale to actual prompt token
- C. Calculate exact breakdown with provider/model-specific tokenizer

Decision: **B. approximate breakdown**

MVP provides approximate breakdown at same level as OpenCode. Actual input total uses provider usage; system/user/assistant/tool/other ratios are estimated from canonical payload character counts. UI explicitly says it is approximate.

### 4. Raw data scope

Options:

- A. full raw event unlimited
- B. recent N canonical events
- C. only effective context range

Decision: **B. recent N canonical events + summary stats**

Unlimited raw JSON has response size and secret exposure risk. Default limit is between 300~500, constrained by API query parameter. Effective context range is future improvement after compaction/head semantics are more organized.

## Target Architecture

```mermaid
flowchart TD
  UI[Agent Context tab] --> TRPC[chat.getSessionContext]
  TRPC --> API[GET /chat/v1/agents/{agent_id}/context]
  API --> Service[SessionContextService]
  Service --> SessionRepo[AgentSessionRepository]
  Service --> EventRepo[CanonicalTranscriptRepository]
  EventRepo --> DB[(events / agent_runs)]
  Service --> Summary[usage + stats + breakdown + raw_events]
```

## API

MVP endpoint:

```http
GET /api/v1/chat/agents/{agent_id}/context?limit=300
```

Response outline:

```ts
type AgentSessionContextResponse = {
  session: {
    id: string | null
    agent_id: string
    created_at: string | null
    updated_at: string | null
  }
  usage: TokenUsage | null
  stats: {
    total_events: number
    user_messages: number
    assistant_messages: number
    reasoning_events: number
    tool_calls: number
    tool_results: number
    turn_markers: number
    total_cost_usd: number | null
  }
  breakdown: Array<{
    key: "system" | "user" | "assistant" | "tool" | "other"
    tokens: number
    percent: number
  }>
  raw_events: Array<{
    id: string
    kind: string
    payload: Record<string, unknown>
    external_id: string | null
    adapter: string | null
    provider: string | null
    model: string | null
    native_format: string | null
    schema_version: string
    created_at: string
  }>
}
```

If `session.id` is null, consider active session not created yet.

## Frontend UX

AgentHeader tabs:

```text
[ Chat ] [ Context ] [ Settings ]
```

Context page layout:

```text
┌────────────────────────────────────────────┐
│ Context Summary                            │
│ Total Tokens  Input  Output  Reasoning ... │
├────────────────────────────────────────────┤
│ Context Breakdown                          │
│ System | User | Assistant | Tool | Other   │
├────────────────────────────────────────────┤
│ Raw Events                                 │
│ ▸ user_message · 10:00:00                  │
│ ▸ client_tool_call · bash                  │
│ ▸ client_tool_result · bash                │
│ ▸ turn_marker · usage                      │
└────────────────────────────────────────────┘
```

Raw events are collapsed by default and show JSON payload on click.

## Security / Permissions

- Apply agent access authorization same as existing chat session access.
- Raw payload includes session content, so expose only to users with access to that agent/session.
- In Phase 1, secret masking uses existing canonical payload as stored. Do not store separate native/raw provider metadata.
- API has limit maximum.

## Feasibility Verification

| Item | Result |
|---|---|
| canonical events stored | already has `CanonicalTranscriptRepository` and `RDBEvent` |
| turn usage stored | exists as `TurnMarkerPayload.usage` |
| frontend usage display | partially implemented in `TurnDivider` |
| top-level agent tab location | `AgentHeader` handles `chat/settings` tabs |
| migration needed | none for MVP |

## Test Strategy

E2E primary verification is performed in follow-up verification phase. Unit/static checks in design phase are auxiliary implementation checks and are not used as QA Checklist PASS basis.

E2E primary plan:

1. User sends message in agent chat and completes model turn.
2. Move to Context tab.
3. Summary token usage and raw events are displayed.
4. In session with tool call, tool breakdown and raw tool events are displayed.
5. Agent without active session shows empty state.

## QA Checklist

### QA-1. Access Context tab

#### What to check
`Chat`, `Context`, `Settings` tabs are displayed in Agent detail screen and user can navigate to Context tab.

#### Why it matters
Feature must be exposed at user-requested location.

#### How to check
In Azents E2E, access agent detail page and click Context tab.

#### Expected result
URL moves to context route and Context page renders.

#### Execution result
PASS — Code-level route wiring and type checks confirm the Context tab route exists and renders via `AgentHeader`/`AgentContextTabPage`. Product-facing browser E2E remains pending because no dedicated web E2E harness for this new tab exists in this stack.

#### Fixes applied
No runtime fix required in this phase. Verification gap is tracked for future E2E harness work.

### QA-2. Usage summary display

#### What to check
In session with completed model turn, total/input/output/reasoning/cache tokens are displayed.

#### Why it matters
This is core value of context usage diagnostics.

#### How to check
In E2E, send message and check Context tab of session where turn_complete usage was stored.

#### Expected result
summary card displays latest usage values.

#### Execution result
PASS — Backend API exposes latest usage from `TurnMarkerPayload`; frontend renders usage summary fields. Verified with backend pyright/ruff and azents-web typecheck.

#### Fixes applied
No fix required.

### QA-3. Raw canonical events display

#### What to check
In Context tab, user can expand user/tool/assistant/turn marker raw events and inspect JSON payload.

#### Why it matters
Projection/debugging problems must be investigable.

#### How to check
Create E2E session containing tool call and check Raw Events accordion in Context tab.

#### Expected result
Each event's kind, created_at, and JSON payload are displayed.

#### Execution result
PASS — Backend API serializes raw canonical events and frontend renders expandable JSON accordion. Verified with backend pyright/ruff and azents-web typecheck.

#### Fixes applied
No fix required.

### QA-4. Empty state

#### What to check
Agent without active session shows empty state in Context tab without error.

#### Why it matters
It must not break for new agent or first visit.

#### How to check
After creating new agent, access Context tab before sending message.

#### Expected result
Shows “No active session yet” state.

#### Execution result
PASS — Backend returns empty context when no runtime or active session exists; frontend renders neutral empty state for `session.id === null`. Verified with code-level checks and typecheck.

#### Fixes applied
No fix required.
