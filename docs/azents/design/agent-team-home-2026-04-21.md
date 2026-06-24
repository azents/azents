---
title: "Agent-Team Home Design"
tags: [frontend, nointern-web, navigation, UX]
created: 2026-04-21
updated: 2026-04-21
implemented: 2026-04-21
issue: "#2779"
supersedes: docs/nointern/design/home-as-agent-list-2026-04-21.md
---

> **Implemented / archived** — implementation PRs #2902 (design), #2903 (phase 1 Home),
> #2904 (phase 2 Sidebar), #2905 (cleanup). Migrated "Our Team Agents" Home UI based on design handle
> `M1P3PGa_LxPQZVVCJmKvPg`.

# Agent-Team Home Design

## Overview

`home-as-agent-list` simply replaced Home with `AgentList` (cards + SegmentedControl), but the design team proposed a follow-up Home that emphasizes the **team view** nature of "Our Team Agents." Sidebar also exposes only **pinned + recent** instead of all agents, and Home takes the role of full directory.

Design handle: `api.anthropic.com/v1/design/h/M1P3PGa_LxPQZVVCJmKvPg` — `NoIntern+Agent-Centric+Nav.html`. File structure:

- `home.jsx` — TeamStatRow / AgentCard / SubagentRow / HomePage
- `sidebar.jsx` — Sidebar (pinned + recent + "View all")
- `data.jsx` — mock data (emoji, color, owner, sessionsCount, lastActiveAt, busy, subagent metrics included)

## User Scenarios

1. **Enter Home** → "Our Team Agents" header + 4 team stat cards + Agents/Subagents/All tabs
2. **Agent view** → 3-col card grid (avatar + name + provider + description + toolkit badges + subagent count + last activity + owner)
3. **Subagent view** → 1-col list (avatar + name + parent agent link + metrics + chat unavailable notice)
4. **All view** → both sections (separated by SectionHeader)
5. **Search** → partial match against name/description/parent name
6. **Inactive toggle** → whether to include disabled agents (shown only when any exist)
7. **Card click** → navigate to agent detail `chat` tab
8. **New agent button** → `/agents/new`

Sidebar shows only pinned/recent up to 8 + quick search + "View all agents (N)" footer button → Home.

## Data Mapping — Design Expectations ↔ Current Backend

| Design field | Current data | Handling policy |
|---|---|---|
| `agent.id, name, description, enabled, role, type, llm_provider_model` | `AgentResponse` | Use as-is |
| `agent.emoji, color` | none | Replace with name-hash-based color/initial from `AgentAvatar` |
| `agent.providerLabel` | `llm_provider_model.provider` (`openai`, `anthropic`, …) | Reuse existing `providerLabel` mapping |
| `agent.toolkits` | none (not included in current FE data) | Omit in first version. Review need to add to `agent.list` response in Phase 3+ |
| `agent.sessionsCount, lastActiveAt, sessions` | filter `chat.listSessions` by agent_id → count, max updated_at | Derive on client |
| `agent.busy` | none | Omit first (real-time connection state has ownership issue with WebSocket) |
| `agent.owner` | none | Omit first |
| `subagent.parentId` | `agentSubagent.list` links (but queried per agent) | Call `agentSubagent.list({agentId})` for all agents and build reverse map, or infer from SUBAGENT role agents — need review of fallback |
| `subagent.description` (role description) | agent `description` + link description | Link description is parent-specific context, so Home uses agent `description` |
| `subagent.callsThisWeek, avgLatency, lastCalledAt` | none (no backend telemetry) | Omit first, use "—" placeholder or simple label |

## Architecture

### Route / Page Hierarchy

```
/w/{handle}
 └─ features/workspace/pages/WorkspaceHomePage.tsx  (entry, createReactContainer)
     ├─ containers/useWorkspaceHomeContainer.ts      (merge agent.list + chat.listSessions + agentSubagent.list)
     └─ components/WorkspaceHome.tsx                 (UI — header + stats + tabs + grid/list)
         ├─ WorkspaceHomeStatsRow.tsx                (4 stat cards)
         ├─ AgentTeamCard.tsx                        (one card in 3-col grid)
         ├─ SubagentTeamRow.tsx                      (one row in 1-col list)
         └─ WorkspaceHomeEmpty.tsx                   (no search result / empty state)
```

Existing `features/agents/AgentListPage.tsx` remains (reused inside agent detail/edit). Home no longer renders `AgentListPage` as-is and uses new `WorkspaceHomePage`.

### State Definition (ADT)

```ts
type WorkspaceHomeState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      agents: EnrichedAgent[];      // calculated sessionsCount, lastActiveAt
      subagents: EnrichedSubagent[]; // injected parentAgent
    };
```

### URL State

- `view` — `agents` | `subagents` | `all`, default `agents`. Persist via URL `?view=...`.
- `q` — search term (start with internal useState instead of URL state. Move to URL after confirming demand for search bookmark).
- `showOff` — disabled toggle (internal state).

### Data Fetching Strategy

1. `trpc.agent.list({handle})` → all agents (primary + subagent) once
2. `trpc.chat.listSessions({handle})` → all sessions once → map into `Map<agent_id, sessions[]>`
3. Subagent list: filter with `agents.filter(a => a.role === "subagent")` + **parent mapping**: call `trpc.agentSubagent.list({handle, agentId})` in parallel for each primary agent. Build reverse map `subagent_id → parent_agent`.
   - This is N+1 calls, but primary agent count is expected to be dozens or less per workspace — acceptable.
   - Later review adding `agentSubagent.listWorkspace({handle})` as single call.

## Change Scope

### Keep

- `features/agents/AgentListPage` — verify with grep whether use sites remain (may be deprecated). Currently `/agents` is redirect-only and Home directly renders, so Home was only AgentListPage import. In Phase 1 after replacing Home, **keep** AgentListPage file in this issue (consider deletion in Phase 4 cleanup after confirming no other references).

### Change

| File | Change |
|---|---|
| `app/(app)/w/[handle]/page.tsx` | `<AgentListPage>` → `<WorkspaceHomePage>` |
| `features/workspace/pages/WorkspaceHomePage.tsx` | **new** |
| `features/workspace/containers/useWorkspaceHomeContainer.ts` | **new** |
| `features/workspace/components/WorkspaceHome.tsx` | **new** |
| `features/workspace/components/WorkspaceHomeStatsRow.tsx` | **new** |
| `features/workspace/components/AgentTeamCard.tsx` | **new** |
| `features/workspace/components/SubagentTeamRow.tsx` | **new** |
| `features/agents/components/AgentSidebarSection.tsx` | limit to pinned (sessionsCount > 10) + recent (max 8), add "View all agents" footer button |
| `messages/*.json` | new keys such as `workspace.home.team.*`, `workspace.home.stats.*`, `workspace.home.filter.*` |

### Remove / Defer

- `agent.role` filter moves to Home tabs → SegmentedControl filter in `AgentListPage` is no longer exposed (`/agents` redirects, so no user impact). See section above for AgentListPage file itself.

## First Scope / Deferred

| Item | First | Deferred |
|---|---|---|
| Header / team stats / tabs | ✅ | — |
| Agent card grid (avatar + name + description + last activity) | ✅ | — |
| Toolkit badges | — | expose if agent.list response includes toolkit slug |
| "busy" pulse | — | requires global WebSocket state — separate issue |
| Owner | — | omit because agent owner concept does not exist; future primary owner in agent admin |
| Subagent metrics (calls/latency) | — | separate telemetry issue (related #2685) |
| Search | ✅ | — |
| Inactive toggle | ✅ | — |
| Activity feed button | — | place area only and disable on click |
| Sidebar pinned + recent limit | ✅ (Phase 2) | — |
| Sidebar "View all" button | ✅ (Phase 2) | — |

## Ship Phases

- **`[1/4] docs`** — this document + superseded note transition for `home-as-agent-list.md` (implemented cleanup later)
- **`[2/4] phase 1 — Home`** — `WorkspaceHomePage` + container + components, connect `/w/{handle}`
- **`[3/4] phase 2 — Sidebar`** — `AgentSidebarSection` pinned+recent logic + "View all" footer
- **`[4/4] cleanup`** — clean up implemented status of this document + superseded chain + decide whether to remove `AgentListPage` if possible

## Testenv / Spec Impact

- **testenv**: N/A (FE only)
- **spec**: N/A. `docs/nointern/spec/**` code_paths are backend-only.

## Reviewer Checkpoints

- Whether `useWorkspaceHomeContainer` follows existing container pattern (ADT state).
- Whether data mapping follows "omit missing fields in first version" principle.
- Whether sidebar change reuses existing AgentSidebarRow component.
- Whether URL state (`?view=`) default value does not remain in URL.
- 4 i18n locales updated together.
