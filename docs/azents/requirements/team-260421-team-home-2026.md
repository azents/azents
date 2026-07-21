---
title: "Agent-Team Home Historical Requirements Reconstruction"
created: 2026-04-21
implemented: 2026-04-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: team-260421
historical_reconstruction: true
migration_source: "docs/azents/design/agent-team-home-2026-04-21.md"
---

# Agent-Team Home Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `team-260421`
- Source: `docs/azents/design/team-260421-team-home-2026.md`
- Historical source date basis: `2026-04-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

`home-as-agent-list` simply replaced Home with `AgentList` (cards + SegmentedControl), but the design team proposed a follow-up Home that emphasizes the **team view** nature of "Our Team Agents." Sidebar also exposes only **pinned + recent** instead of all agents, and Home takes the role of full directory.

Design handle: `api.anthropic.com/v1/design/h/M1P3PGa_LxPQZVVCJmKvPg` — `NoIntern+Agent-Centric+Nav.html`. File structure:

- `home.jsx` — TeamStatRow / AgentCard / SubagentRow / HomePage
- `sidebar.jsx` — Sidebar (pinned + recent + "View all")
- `data.jsx` — mock data (emoji, color, owner, sessionsCount, lastActiveAt, busy, subagent metrics included)

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

1. **Enter Home** → "Our Team Agents" header + 4 team stat cards + Agents/Subagents/All tabs
2. **Agent view** → 3-col card grid (avatar + name + provider + description + toolkit badges + subagent count + last activity + owner)
3. **Subagent view** → 1-col list (avatar + name + parent agent link + metrics + chat unavailable notice)
4. **All view** → both sections (separated by SectionHeader)
5. **Search** → partial match against name/description/parent name
6. **Inactive toggle** → whether to include disabled agents (shown only when any exist)
7. **Card click** → navigate to agent detail `chat` tab
8. **New agent button** → `/agents/new`

Sidebar shows only pinned/recent up to 8 + quick search + "View all agents (N)" footer button → Home.

## Supporting Scenarios

1. **Enter Home** → "Our Team Agents" header + 4 team stat cards + Agents/Subagents/All tabs
2. **Agent view** → 3-col card grid (avatar + name + provider + description + toolkit badges + subagent count + last activity + owner)
3. **Subagent view** → 1-col list (avatar + name + parent agent link + metrics + chat unavailable notice)
4. **All view** → both sections (separated by SectionHeader)
5. **Search** → partial match against name/description/parent name
6. **Inactive toggle** → whether to include disabled agents (shown only when any exist)
7. **Card click** → navigate to agent detail `chat` tab
8. **New agent button** → `/agents/new`

Sidebar shows only pinned/recent up to 8 + quick search + "View all agents (N)" footer button → Home.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
