---
title: "Agent-Centric Navigation Design"
tags: [frontend, nointern-web, navigation, UX]
created: 2026-04-20
updated: 2026-04-21
implemented: 2026-04-21
issue: "#2779"
superseded_by: docs/nointern/design/home-as-agent-list-2026-04-21.md
---

> **Superseded** — IA was reorganized by subsequent `home-as-agent-list` design,
> and the separate `/agents` structure plus sidebar "Subagents" entry were removed.
> This document remains only as reference history.

# Agent-Centric Navigation Design

## Overview

Reorganize nointern-web workspace navigation as "agent-centric". From current flat NavLink (`Home/Members/Agents/Toolkits/Shell/Chat/Settings/Profile`) + global `/chat` structure, promote agent as primary navigation unit and place `Chat` and `Settings` as tabs under each agent.

Original design: `/tmp/design-2779/nointern/project/NoIntern Agent-Centric Nav.html` (Claude Design bundle).
Discussion record: [`docs/nointern/adr/0009-agent-centric-nav.md`](../../adr/0009-agent-centric-nav.md).

## User Scenarios

1. **Enter workspace** → sidebar shows list of agents user belongs to
2. **Select agent** → recent sessions for that agent expand
3. **Click specific session** → enter chat view (Chat tab)
4. **Configure same agent** → switch to Settings tab on same page
5. **Create new agent** → sidebar "+" button → existing `/agents/new`
6. **Share bookmark** — tab and session are reflected in URL and can be shared as-is

## Architecture

```mermaid
graph TB
  Sidebar["WorkspaceSidebar (rewrite)"]
  AgentPage["/w/{h}/agents/{id}"]
  ChatTab["Chat tab"]
  SettingsTab["Settings tab"]

  Sidebar -->|select agent| AgentPage
  AgentPage -->|/chat/{sessionId?}| ChatTab
  AgentPage -->|/settings/{section?}| SettingsTab

  ChatTab --> SessionsPanel["SessionsPanel (agent filtered)"]
  ChatTab --> ChatView["ChatView (existing reuse)"]

  SettingsTab --> SettingsSubNav["Subnav (general/model/prompt/toolkits/subagents/access/integrations/danger)"]
  SettingsTab --> SectionContent["section component (reuse existing AgentForm)"]
```

## Route Structure

**No backward compatibility — clean delete existing routes.**

```
/w/{handle}/agents                                # keep existing list
/w/{handle}/agents/new                            # keep existing new agent
/w/{handle}/agents/{agentId}                      # → automatically enter /chat (default tab)
/w/{handle}/agents/{agentId}/chat                 # session landing
/w/{handle}/agents/{agentId}/chat/{sid}           # specific session
/w/{handle}/agents/{agentId}/settings             # → /settings/general
/w/{handle}/agents/{agentId}/settings/{section}   # edit per section

# removed (delete)
/w/{handle}/chat                                  # remove
/w/{handle}/agents/{agentId}/edit                 # remove (= /settings/general)
```

**Post-removal handling:**
- Delete existing `/chat`, `/agents/{id}/edit` route directories.
- Move necessary UI from route-related files (`features/chat/ChatPage.tsx`, `AgentFormPage.tsx`) to new feature; remove unnecessary files.
- Update every backend-provided external deep link URL (see "Backend URL reference updates" below).

## Component Structure Changes

### New

```
src/
├── app/(app)/w/[handle]/agents/[agentId]/
│   ├── layout.tsx               (new: agent load + header/tab shell)
│   ├── page.tsx                 (new: /chat redirect)
│   ├── chat/
│   │   ├── page.tsx             (new: landing without session)
│   │   └── [sessionId]/
│   │       └── page.tsx         (new: specific session)
│   └── settings/
│       ├── page.tsx             (new: /general redirect)
│       └── [section]/
│           └── page.tsx         (new: per-section page)
├── features/agents/
│   ├── AgentDetailPage.tsx            (new: AgentHeader + Tabs shell)
│   ├── AgentChatTabPage.tsx           (new)
│   ├── AgentSettingsTabPage.tsx       (new)
│   ├── containers/
│   │   └── useAgentDetailContainer.ts (new: agent load + active tab resolving)
│   └── components/
│       ├── AgentHeader.tsx            (new)
│       ├── AgentAvatar.tsx            (new: name hash → color/initial)
│       ├── AgentSidebarSection.tsx    (new: expandable list for sidebar)
│       └── AgentSidebarRow.tsx        (new: each agent row + inline sessions)
└── features/chat/
    └── components/
        └── AgentSessionsPanel.tsx     (new: single-agent session list; simplified SessionSidebar logic)
```

### Changed

- `shared/components/WorkspaceSidebar.tsx` — integrate agent list section. Keep existing flat NavLink but insert `AgentSidebarSection` where "Agents" NavLink was. Remove "Chat" NavLink.
- `shared/components/WorkspaceShell.tsx` — no structural change (layout unchanged).
- `features/agents/AgentFormPage.tsx` — partial reuse in `/settings/general`, etc. (reuse section components, remove full-page shell).
- `features/chat/ChatPage.tsx` — remains at global `/chat`, but redirects to `/agents/{a}/chat/{s}` when `?session=X` arrives.
- `trpc/routers/chat.ts` — no server change. client filtering.

### Removed

- Agent dropdown (`Select`) in `features/chat/components/SessionSidebar.tsx` — even global chat page keeps agent selection UI but changes to "select a new agent to start" landing style.

## Data Flow

### Agent detail load (layout.tsx)

```typescript
// app/(app)/w/[handle]/agents/[agentId]/layout.tsx (server component)
const agent = await trpc.agent.get({ handle, agentId });
// 404 handling → notFound()
return <AgentDetailShell agent={agent}>{children}</AgentDetailShell>;
```

### Sidebar agent + session data (client)

```typescript
// features/agents/containers/useAgentSidebarContainer.ts
const agentsQuery = trpc.agent.list.useQuery({ handle });
const sessionsQuery = trpc.chat.listSessions.useQuery({ handle });

// derive: agent → recent sessions
const agentsWithSessions = useMemo(() => {
  const sessions = sessionsQuery.data?.items ?? [];
  return (agentsQuery.data?.items ?? [])
    .filter(a => a.role !== "subagent")
    .map(agent => ({
      ...agent,
      sessions: sessions
        .filter(s => s.agent_id === agent.id)
        .slice(0, 4),  // inline 4
      sessionCount: sessions.filter(s => s.agent_id === agent.id).length,
    }));
}, [agentsQuery.data, sessionsQuery.data]);
```

### Chat tab data

```typescript
// features/agents/containers/useAgentChatContainer.ts
const sessionsQuery = trpc.chat.listSessions.useQuery({ handle });
const agentSessions = sessionsQuery.data?.items.filter(s => s.agent_id === agentId) ?? [];
// activeSessionId from params
// reuse existing useChatSessionContainer with fixed agent
```

### Settings tab data

Reuse existing `useAgentFormContainer`. Mount only needed fieldset per Section.

## UI/UX

### Sidebar (common for Drawer and desktop)

```
┌──────────────────────────────┐
│ [M] Azents        ▽        │  WorkspaceHeader
│ @azents                    │
├──────────────────────────────┤
│ 🏠 Home                      │
│ 👥 Members                 24│
├──────────────────────────────┤
│ Agents                [+]    │
│ ┌─[Search]───────────────┐   │
│ └────────────────────────┘   │
│                              │
│ ▼ 🔍 Code Reviewer      ●    │  active + expanded
│   💬 PR #482 review     ●    │
│   💬 Build error             │
│   💬 Schema refactor         │
│   +2 more                    │
│ ▶ 📎 Reference Researcher    │
│ ▶ 🗒️  Meeting Notetaker      │
│ ▶ 📡 Community Monitor  off  │
├──────────────────────────────┤
│ 🛠️  Toolkits                 │
│ >_ Shell environment         │
│ ⚙  Workspace settings        │
├──────────────────────────────┤
│ [J] Jung Chaewon             │
│     admin             [👤]   │
└──────────────────────────────┘
```

Mantine conversion:
- Workspace header: `Group` + `Text`
- Nav items (Home/Members/Toolkits/Shell/Workspace settings): reuse existing `NavLink`
- Agent section: custom implementation (`AgentSidebarSection` + `AgentSidebarRow`)
- Search: Mantine `TextInput`
- Avatar: `AgentAvatar` (name hash → `Mantine.Avatar` color)
- Expand chevron: `ActionIcon` + `IconChevronRight` rotate

### AgentDetailShell (layout)

```
┌───────────────────────────────────────────────────┐
│ [🔍]  Code Reviewer  [● active] [public]  [Anthropic · claude-sonnet-4-5] [⋯] │
│      Check style, logic, and security issues on PRs and leave comments        │
├───────────────────────────────────────────────────┤
│ [💬 Chat (5)]  [⚙  Settings]                                           │
├───────────────────────────────────────────────────┤
│                                                   │
│    (Chat tab or Settings tab content)             │
│                                                   │
└───────────────────────────────────────────────────┘
```

Mantine conversion:
- Header: `Group` + `AgentAvatar` + `Title` + `Badge` + `ActionIcon.Group`
- Tabs: `Tabs` (Mantine)

### Chat tab

```
┌──────────────┬─────────────────────────────────┐
│ [+ New chat] │ PR #482 review       ● connected│
├──────────────┤─────────────────────────────────┤
│ Conversations│                                 │
│ (5)          │   (existing ChatView content)   │
│ 💬 PR #482   │                                 │
│ 💬 Build err │                                 │
│ ...          │                                 │
│              │                                 │
└──────────────┴─────────────────────────────────┘
```

Mobile (`< sm`):
- Session panel Drawer (from right, toggle button in AgentHeader)
- Default screen: ChatView only

### Settings tab

```
┌────────────────┬─────────────────────────────────┐
│ Settings       │                                 │
│                │  General information            │
│ ● General info │  ┌────────────────────────────┐ │
│   Model & LLM  │  │ Icon: [🔍]                 │ │
│   System prompt│  │ Name: [Code Reviewer    ]  │ │
│   Toolkits     │  │ Description: [──────────]  │ │
│   Subagents    │  └────────────────────────────┘ │
│   Access       │                                 │
│   Integrations │  Active state                   │
│   Danger zone  │  ┌────────────────────────────┐ │
│                │  │ ● Enable agent [on]        │ │
│                │  └────────────────────────────┘ │
│                │                                 │
│                │               [Cancel] [Save]  │
└────────────────┴─────────────────────────────────┘
```

Mobile (`< sm`):
- Subnav → select section with `Select`

### AgentAvatar implementation

```typescript
function nameToAvatarColor(name: string): string {
  // Mantine color index (10 colors)
  const colors = ["blue", "red", "green", "grape", "cyan", "teal", "pink", "orange", "violet", "indigo"];
  const hash = name.split("").reduce((h, c) => h + c.charCodeAt(0), 0);
  return colors[hash % colors.length];
}

function getInitial(name: string): string {
  return name.charAt(0).toUpperCase();
}

// <Avatar color={nameToAvatarColor(agent.name)}>{getInitial(agent.name)}</Avatar>
```

## Mantine Theme Mapping

**Current theme check result** (`shared/theme.ts`):
- `primaryColor: "mono"` (warm gray custom palette)
- `primaryShade: { light: 9, dark: 0 }`
- "Dark Canvas" design — warm-tone monochrome

Prototype's green accent (`#2f6f4f`) does not match this app's existing design language. **When translating design, replace prototype's green accent with app's mono primary**:

| Prototype | Mapping strategy |
|---|---|
| `--accent #2f6f4f` (green) | `var(--mantine-primary-color-filled)` (automatically mono family) |
| `--accent-weak #e8f1ec` | `var(--mantine-primary-color-light)` |
| `--accent-strong #235339` | `var(--mantine-primary-color-filled-hover)` |
| Active tab / button accent | Mantine `color="primary"` |
| Unread dot / online indicator | Keep Mantine `green` family (status indicator needs semantic color, not mono) |

**Rationale**: consistency > prototype fidelity. Users are already used to app's warm mono language, and introducing green creates visual inconsistency. If designer asks for "other pages using same design system", guide based on mono palette.

CSS variable usage rules (CLAUDE.md compliance):
- No hardcoded hex (except meaningful colors for status dots)
- Common variables: `var(--mantine-color-body)`, `var(--mantine-color-default-border)`, `var(--mantine-color-dimmed)`
- Text color: `<Text c="dimmed">`

## Backend URL Reference Updates

Places where frontend URL is directly generated in backend code — all need update.

### Update target: `/w/{handle}/chat?session={sid}` → `/w/{handle}/agents/{agent_id}/chat/{sid}`

These adapters already have `self._agent_id` field, so including it in URL is trivial:

| File | Lines | Usage |
|---|---|---|
| `python/apps/nointern/src/nointern/worker/adapters/slack.py` | 621-622 | "View in Web" button (control message create) |
| `python/apps/nointern/src/nointern/worker/adapters/slack.py` | 697-698 | "View in Web" button (control message update) |
| `python/apps/nointern/src/nointern/worker/adapters/discord.py` | 495-496 | "View in Web" button (Discord embed) |

Change example:
```python
# Before
f"{self._web_url}/w/{self._workspace_handle}/chat?session={self._session_id}"

# After
f"{self._web_url}/w/{self._workspace_handle}/agents/{self._agent_id}/chat/{self._session_id}"
```

### URLs kept unchanged

Following paths are outside this issue scope and remain unchanged:

| Path | Purpose | File |
|---|---|---|
| `/w/{handle}/account/link/slack` | Slack account link | slack adapter/handlers, discord handlers |
| `/w/{handle}/account/link/discord` | Discord account link | discord adapter/handlers |
| `/w/{handle}/toolkit/{toolkit_id}/setup` | Toolkit OAuth setup | slack/discord adapter |
| `/w/{handle}/settings/github-pat` | GitHub PAT guidance | github runtime tool |
| `/w/{handle}/settings/members` | Workspace member management | email service (invitation) |
| `/login?next=/workspaces` | redirect after login | email service |

### Frontend internal reference updates

| File | Change |
|---|---|
| `features/agents/components/AgentList.tsx:211` | `${basePath}/${agent.id}/edit` → `${basePath}/${agent.id}` (= default chat tab) or `${basePath}/${agent.id}/settings` |
| `shared/components/WorkspaceSidebar.tsx:46,57,118` | remove Chat NavLink |
| `features/agents/containers/useAgentFormContainer.ts:243,263` | remove (AgentFormPage no longer used) |
| `app/(app)/w/[handle]/agents/[agentId]/edit/page.tsx` | delete directory |
| `app/(app)/w/[handle]/chat/page.tsx` | delete directory |

## API

All needed APIs already exist. No server change.

| Behavior | tRPC |
|---|---|
| agent list | `agent.list` |
| agent detail | `agent.get` |
| agent update | `agent.update` |
| agent delete | `agent.remove` |
| session list (workspace) | `chat.listSessions` |
| session messages | `chat.listMessages` |
| session delete | `chat.deleteSession` |
| WebSocket ticket | `chat.getConnectionInfo` |
| admin management | `agent.listAdmins/addAdmin/removeAdmin` |
| toolkit connection (existing) | `toolkit.*` |
| subagent (existing) | `agentSubagent.*` |
| Slack connection (existing) | `slack-installation.*` |
| LLM provider list | `llm-provider-integration.*`, `llm-provider-model.*` |
| Shell environments | `shellEnvironment.*` |

## i18n

Add following keys to `messages/` files (4 locales required):

```json
{
  "workspace.sidebar.agentsSectionTitle": "Agents",
  "workspace.sidebar.newAgent": "New agent",
  "workspace.sidebar.searchAgents": "Search agents",
  "workspace.sidebar.moreSessions": "{count} more",

  "workspace.agents.detail.tabs.chat": "Chat",
  "workspace.agents.detail.tabs.settings": "Settings",
  "workspace.agents.detail.status.enabled": "Active",
  "workspace.agents.detail.status.disabled": "Inactive",

  "workspace.agents.chat.newChat": "New chat with {agentName}",
  "workspace.agents.chat.conversations": "Conversations",
  "workspace.agents.chat.empty": "No conversations yet. Start with the new chat button.",

  "workspace.agents.settings.sections.general": "General information",
  "workspace.agents.settings.sections.model": "Model & LLM",
  "workspace.agents.settings.sections.prompt": "System prompt",
  "workspace.agents.settings.sections.toolkits": "Toolkits",
  "workspace.agents.settings.sections.subagents": "Subagents",
  "workspace.agents.settings.sections.access": "Access control",
  "workspace.agents.settings.sections.integrations": "Integrations",
  "workspace.agents.settings.sections.danger": "Danger zone"
}
```

## Infrastructure

**No changes**. Frontend-only change.

## Feasibility Verification

| Verification item | Method | Result |
|---|---|---|
| `ConversationSessionResponse.agent_id` exists | code check (`api/public/chat/v1/__init__.py:593-604`) | ✅ |
| `agent.list` API exists | `trpc/routers/agent.ts:53-73` | ✅ |
| existing `ChatView` reusable | `features/chat/components/ChatView.tsx` | ✅ — only props adjustment when session fixed |
| existing `AgentForm` section components reusable | `AgentToolkitSection/AgentSubagentSection/AgentAdminSection/AgentSlackSection` | ✅ |
| Mantine color scheme dark supported | `ColorModeSwitcher.tsx` | ✅ |
| Mobile drawer pattern exists | `WorkspaceShell.tsx` | ✅ |
| WorkspaceShell structure change unnecessary | layout.tsx analysis | ✅ (only sidebar internal change) |
| new route nested layout possible | Next.js 16 App Router | ✅ |
| existing `/chat?session=X` → `/agents/{a}/chat/{s}` redirect | need load session's agent_id | ✅ — client-side redirect component |

**Risks and mitigation:**

| Risk | Impact | Mitigation |
|---|---|---|
| Initial load slow if session list grows to entire workspace scale | medium | Monitor tRPC query + client group-by performance. Add server per-agent endpoint if 1000+ sessions occur |
| Existing `/chat` bookmark user confusion | low | Graceful redirect + landing guidance "select agent" |
| Validation fragmentation when splitting AgentForm sections | medium | Keep React Hook Form + common schema, use tab-wide onSubmit not per-section onSubmit |
| Mantine Tabs and Next.js router synchronization | low | `router.push(...)` in Mantine Tabs `onChange` |
| Session Drawer usability on narrow mobile | medium | E2E test + Playwright viewport verification |

## testenv QA Scenarios

```python
# testenv/nointern/scenarios/agent_centric_nav_test.py

import pytest

from testenv.nointern.client import NointernClient


def test_agent_detail_chat_tab_renders_sessions(seed: NointernClient):
    """Agent detail /chat tab must show only sessions for that agent."""
    user = seed.auth.create_user()
    ws = seed.workspace.create(user)
    agent_a = seed.agent.create(ws, user, name="Reviewer")
    agent_b = seed.agent.create(ws, user, name="Researcher")

    # Create sessions for both agents
    sess_a1 = seed.chat.ensure_session(user, agent_a, title="PR #1 review")
    sess_a2 = seed.chat.ensure_session(user, agent_a, title="PR #2 review")
    sess_b = seed.chat.ensure_session(user, agent_b, title="UX research")

    # Enter Chat tab (simulate web path — Playwright handles UI render)
    sessions = seed.chat.list_sessions(user, ws)
    agent_a_sessions = [s for s in sessions if s.agent_id == agent_a.id]

    assert len(agent_a_sessions) == 2
    assert all(s.agent_id == agent_a.id for s in agent_a_sessions)
    assert not any(s.id == sess_b.id for s in agent_a_sessions)


def test_agent_settings_tab_preserves_form_values(seed: NointernClient):
    """Form values must be preserved when moving between sections in Settings tab."""
    user = seed.auth.create_user()
    ws = seed.workspace.create(user)
    agent = seed.agent.create(
        ws, user,
        name="Original Name",
        description="Original description",
        system_prompt="Original prompt",
    )

    # UI verification with Playwright:
    # 1) change name (unsaved) in /agents/{id}/settings/general
    # 2) move to /agents/{id}/settings/prompt
    # 3) return to /agents/{id}/settings/general → changed name preserved
    # 4) save button → verify agent.get result

    # (This Python scenario verifies only API-level consistency)
    updated = seed.agent.update(agent, name="New Name")
    assert updated.name == "New Name"
    assert updated.description == "Original description"  # preserve other fields
```

## testenv Impact

- **Need new seed block**: no. Reuse existing `seed.agent.*`, `seed.chat.*`.
- **Need new scenario/setup doc**: add above `agent_centric_nav_test.py`.
- **Existing scenario breakage**: if E2E hardcodes `/w/{h}/chat` path, redirect handling needed (check landing screen with Playwright `expect(page).toHaveURL(...)`). Needs verification.
- **docker-compose / .env.example / preflight changes**: none.

## Implementation Plan

Create stacked PRs by phase:

1. **PR 1 — Design document** (this document)
2. **PR 2 — Routes + AgentDetailShell** (layout.tsx + tab placeholders, delete existing `/edit` route)
3. **PR 3 — Chat tab implementation** (AgentChatTabPage + Sessions panel + ChatView reuse, delete existing `/chat` route)
4. **PR 4 — Settings tab implementation** (AgentSettingsTabPage + section subnav + reuse existing section components, remove `AgentFormPage`)
5. **PR 5 — Sidebar reorganization** (AgentSidebarSection + AgentSidebarRow + WorkspaceSidebar rework, backend URL reference updates)
6. **PR 6 — i18n + mobile responsive + dark mode polish**

After each PR completion, verify behavior with Playwright MCP + write/execute testenv QA scenario (`scenarios/browser/TC-WEB-xxx.md`) + leave report as issue comment.

## Alternatives Considered

| Alternative | Rejection reason |
|---|---|
| Query string `?tab=` based | lowers URL idiomaticity, cannot leverage Next.js segment routing benefits |
| Parallel Routes | overkill (tabs are mutually exclusive) |
| Server-side per-agent session endpoint | unnecessary at current scale. Add if performance issue occurs |
| Keep sidebar flat list | no meaningful IA change |
| Add agent pinning DB schema | beyond first scope. separate issue |
| Add agent avatar emoji/color DB schema | second phase. first phase covered by name hash |
| Include Discord/clone/activity tabs in first phase | API absent (Discord connect flow/clone endpoint/telemetry) → second phase |
