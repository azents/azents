---
title: "Home-as-agent-list Reorganization Historical Requirements Reconstruction"
created: 2026-04-21
implemented: 2026-04-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: home-260421
historical_reconstruction: true
migration_source: "docs/azents/design/home-as-agent-list-2026-04-21.md"
---

# Home-as-agent-list Reorganization Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `home-260421`
- Source: `docs/azents/design/home-260421-home-list-2026.md`
- Historical source date basis: `2026-04-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Simplify nointern-web workspace IA one more time.

After agent-centric-nav implementation in `#2779`, "agent existence" was spread across 3 places in workspace:

1. Sidebar **Agents** section — primary agent list + inline sessions
2. `/agents` page — full agent card view with SegmentedControl filter (Agents / Subagents / All)
3. Sidebar **Subagents** link — deep link to `/agents?role=subagent`

Updated IA from design team converges these 3 places into **one Home**:

- **Home = agent list** (migrate existing `/agents` UI). URL: `/w/{handle}`.
- Remove `/w/{handle}/agents` route; redirect legacy links to Home.
- Remove sidebar `Subagents` entry — redundant because role filter exists on Home.

Original design URL (`https://api.anthropic.com/v1/design/h/clfqGDcXi0VK7VLvswlJaA`) returned 404 at time of this work. Proceed with only 3 requirements provided by user:

1. Delete `/agents` page
2. Remove sidebar "Subagents" menu
3. Reorganize Home into agent list

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

1. **Enter workspace (`/w/{handle}`)** → immediately show agent card list + Agents/Subagents/All filter
2. **Click card** → `/w/{handle}/agents/{id}/chat` (keep existing agent detail)
3. **New agent** → header `+` button → `/w/{handle}/agents/new` (keep existing route)
4. **Legacy link** `/w/{handle}/agents` or `/w/{handle}/agents?role=subagent` → redirect to Home, preserving query param (`?role=`)

## Supporting Scenarios

1. **Enter workspace (`/w/{handle}`)** → immediately show agent card list + Agents/Subagents/All filter
2. **Click card** → `/w/{handle}/agents/{id}/chat` (keep existing agent detail)
3. **New agent** → header `+` button → `/w/{handle}/agents/new` (keep existing route)
4. **Legacy link** `/w/{handle}/agents` or `/w/{handle}/agents?role=subagent` → redirect to Home, preserving query param (`?role=`)

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

- **Type safety**: Keep existing `AgentListContainerOutput` / `AgentRoleFilter` types.
- **Translation consistency**: Remove i18n keys from all locales (ko/en/ja/fr) at once.
- **No regression**: No behavior change to existing agent detail route / creation route / sidebar inline sessions.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
