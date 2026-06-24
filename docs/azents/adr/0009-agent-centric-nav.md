---
title: "ADR-0009: Agent-Centric Navigation Redesign Discussion"
created: 2026-04-20
tags: [frontend, nointern-web, navigation, UX]
---

# ADR-0009: Agent-Centric Navigation Redesign — Discussion Record

> 📌 **Related design document**: [agent-centric-nav.md](../design/agent-centric-nav.md)

## Background

In issue [#2779](https://github.com/azents/azents/issues/2779), the user (Hardtack) asked for a new navigation IA drawn in Claude Design and requested implementation. The requirements were stated in `chat1.md` included in the design bundle:

> Right now the hierarchy is chat → agent selection, so agents are a lower-level unit. I want it structured as agent → chat and agent → settings.

Current structure: flat sidebar NavLinks for Home, Members, Agents, Toolkits, Shell, Chat, Settings, and Profile, plus a global `/chat` page where an agent is selected from a dropdown.

Target structure: the sidebar primarily shows an agent list, and each agent has a `Chat / Settings` tab structure.

## Discussion Points and Decisions

### 1. Data source for agent-specific sessions

**Question**: Inline recent sessions in the sidebar and the session panel in the Chat tab should show only sessions for this agent. Do we need a new API?

**Options:**

- **A. Add `list_sessions_by_agent` endpoint on the server** — `GET /workspaces/{handle}/agents/{agent_id}/sessions`
- **B. Filter the existing `chat.listSessions` response by `agent_id` on the client** — current response already includes `agent_id`

**Decision: B — client-side filtering**

**Rationale**: `ConversationSessionResponse` already includes an `agent_id` field (`python/apps/nointern/src/nointern/api/public/chat/v1/__init__.py:593-604`). Server ordering is already `updated_at desc`, so `slice(0, 4)` can extract the most recent four sessions. As long as session count is not high, expected to be in the hundreds per workspace, client-side group-by cost is negligible. Add a server endpoint later if performance becomes an issue.

### 2. Route structure

**Question**: How should the agent detail page tabs (Chat/Settings) be reflected in the URL?

**Options:**

- **A. Query string** — `/w/{h}/agents/{id}?tab=chat&session=X`
- **B. Route segments** — `/w/{h}/agents/{id}/chat/{sessionId?}`, `/w/{h}/agents/{id}/settings/{section?}`
- **C. Segments + Parallel routes** — `/w/{h}/agents/{id}/(tabs)/chat` with Next.js Parallel Routes

**Decision: B — route segments**

**Rationale**:

- Matches Next.js App Router conventions.
- Preserves tab state when sharing links or bookmarks.
- `settings/{section}` also puts left subnav items in the URL, enabling deep links inside settings.
- Parallel routes (C) are useful for independent loading states, but tabs are mutually exclusive here, so they are overkill.

**Concrete paths:**

```text
/w/{handle}/agents                              (agent list — keep)
/w/{handle}/agents/new                          (new agent — keep)
/w/{handle}/agents/{agentId}                    (redirect to /chat)
/w/{handle}/agents/{agentId}/chat               (no session — landing)
/w/{handle}/agents/{agentId}/chat/{sessionId}   (specific session)
/w/{handle}/agents/{agentId}/settings           (redirect to /settings/general)
/w/{handle}/agents/{agentId}/settings/{section} (section: general|model|prompt|toolkits|subagents|access|integrations|danger)
```

### 3. Handling the existing `/w/{h}/chat` route

**Question**: What happens to the existing `/chat` page after moving chat under each agent?

**Options:**

- **A. Remove** — clean delete. Update all backend deep links to the new URL.
- **B. Keep as a landing page** — agent selection UI.
- **C. Keep + redirect script for `?session=X`**

**Decision: A — remove**

**Rationale** based on Hardtack feedback: "No backward compatibility needed; clean it up."

- Updating the three backend references that generate `/chat?session=X` URLs (Slack/Discord adapters) also cleans up links coming from the outside world.
- Graceful redirects are technical debt. They must be removed eventually, which would repeat the same design review later.
- Internal bookmarks are low sensitivity for users. Users can learn the new IA.

### 4. Handling the existing `/w/{h}/agents/{id}/edit` route

**Question**: What should happen to the full-page edit form rendered by `AgentFormPage`?

**Options:**

- **A. Remove** — all editing is available in the new settings tabs.
- **B. Keep but redirect to the settings tab.
- **C. Keep in parallel with the new settings.

**Decision: A — remove**

**Rationale**: Avoid duplicate functionality, and no backward compatibility is required. Reuse section components inside `AgentForm`, such as `AgentToolkitSection`, `AgentSubagentSection`, `AgentAdminSection`, and `AgentSlackSection`, as new settings sections. Remove `AgentForm.tsx` and `AgentFormPage.tsx` themselves.

### 3-4 Addendum: Backend URL references

Backend code that generates `/chat?session=X` URLs:

- `python/apps/nointern/src/nointern/worker/adapters/slack.py:621-622, 697-698` (Slack "View in Web" button)
- `python/apps/nointern/src/nointern/worker/adapters/discord.py:495-496` (Discord "View in Web" button)

All already have `self._agent_id`, so updating them to `/agents/{agent_id}/chat/{session_id}` is trivial.

### 5. Sidebar agent expansion versus flat mode

**Question**: The design `tweaks.sidebarMode` contains a `flat` / `expandable` toggle. What should the real implementation use?

**Options:**

- **A. Implement only expandable**
- **B. Implement both and store user preference**
- **C. Implement only flat** for simplicity

**Decision: A — expandable only**

**Rationale**:

- The Tweaks panel is only for the design prototype and live preview. It should not be part of the real app.
- Showing inline sessions is the core of the "agent → chat" structure. Flat mode conceptually regresses from that.
- Store expanded state in `localStorage`; automatically expand the active agent.

### 6. Agent sorting/grouping

**Question**: Should we implement a `pinned` group based on `sessionsCount > 10`?

**Options:**

- **A. Add a "frequently used" group based on session count**
- **B. Implement explicit pinning as a separate feature, requiring DB fields**
- **C. Single list with usage-based sorting only**
- **D. Simple alphabetical/created order**

**Decision: D — simple `updated_at desc`**

**Rationale**:

- Minimize first-scope work. Pinned/favorite functionality requires DB changes.
- Automatic pinning based on session count is not intuitive because users cannot control it.
- Recent agents appearing at the top can be solved simply with `updated_at desc`. Assumes the `agents` table already has `updated_at`; this needs verification.
- Explicit pinning can be a separate issue later.

### 7. Dark mode strategy

**Decision: Use Mantine CSS variables throughout**

Map all hardcoded hex values from the prototype (`#ffffff`, `#2f6f4f`, etc.) to Mantine CSS variables:

| Prototype | Mantine Mapping |
|---|---|
| `--bg #fff` | `var(--mantine-color-body)` |
| `--bg-subtle #fafaf9` | `var(--mantine-color-default)` |
| `--bg-muted #f4f4f2` | `var(--mantine-color-default-hover)` |
| `--border #e8e8e4` | `var(--mantine-color-default-border)` |
| `--text #1a1a19` | `var(--mantine-color-text)` |
| `--text-muted #9a9a95` | `<Text c="dimmed">` |
| `--accent #2f6f4f` | Mantine theme `primaryColor`, with teal or green shade tuning |
| `--accent-weak #e8f1ec` | `var(--mantine-primary-color-light)` |
| `--accent-strong #235339` | `var(--mantine-primary-color-filled)` |

Mantine defaults handle automatic light/dark switching.

### 8. Mobile responsive strategy

**Decision**: Reuse the existing WorkspaceShell Drawer pattern and make only the second panel inside each tab responsive.

| Element | ≥ sm | < sm |
|---|---|---|
| Sidebar | Fixed 272px | Drawer (existing) |
| AgentHeader + Tabs | Horizontal tabs | Keep horizontal tabs with smaller gap |
| Chat tab session panel (300px) | Fixed left panel | Drawer from right, toggled by IconBtn |
| Settings tab subnav (240px) | Fixed left panel | Replace with `Select` dropdown |

Mobile breakpoint: Mantine `sm` (768px).

### 9. Discord, agent cloning, and activity tab

**Decision**:

- **Discord section**: **out of scope** for the first pass. The `discord_agent_config` table exists, but there is no agent-level UI. Split into a separate issue.
- **Agent cloning**: **out of scope** for the first pass. There is no clone endpoint. Low priority.
- **Activity tab**: **out of scope** for the first pass. There is no telemetry aggregation endpoint; depends on issue #2685.
- **System prompt "apply template" button**: functionality is undefined, so **exclude** the button.
- **Agent avatar `emoji`/`color`**: not present in schema. Auto-generate from name: color from name hash → hue, and initial or first character from the name.

### 10. Implementation scope = first pass / second pass

**First pass, handled by this issue**:

1. Rebuild sidebar: agent list + expandable state + inline recent four sessions.
2. Restructure routes: `/agents/{id}/chat/{sessionId?}` + `/agents/{id}/settings/{section?}`.
3. Chat tab: agent-fixed session panel + chat view, removing the dropdown.
4. Settings tab with 8-section subnav, excluding Discord/clone so the implemented list is 7 sections:
   - General / Model & LLM / System Prompt / Toolkits / Subagents / Access / Integrations (Slack) / Danger Zone (delete only)
5. Dark mode support with Mantine variable mapping.
6. Mobile responsive behavior with Drawer/Select.
7. Graceful redirect for existing `/chat` and `/agents/{id}/edit` routes.

**Second pass, separate issues**:

- Activity tab, after telemetry feature release
- Agent cloning
- Discord integration section
- Session unread / snippet
- Persisted agent avatar emoji/color, requiring schema changes
- "Frequently used" pinning
- Redesign of Home/Members/Toolkits/Shell/Workspace Settings pages, after requesting designer options A

## Alternatives Reviewed

| Alternative | Reason Rejected |
|---|---|
| Single-page app with no URL state | Links and bookmarks would not work; goes against App Router conventions |
| Keep existing global `/chat` page and agent dropdown | Does not change the core hierarchy of agent → chat |
| Add server-side per-agent session list endpoint | Overkill at current data scale; add later if needed |
| Automatic pinning based on `sessionsCount` as agent sorting criterion | Not intuitive; explicit pinning is better as a second-pass feature |
| Use accordion for settings subnav | Editing one section at a time is better handled by subnav; mobile replaces it with Select |

## Next Steps

Write the design document (`docs/nointern/design/agent-centric-nav.md`) and proceed with phased stacked PRs.
