---
title: "Session Directory Requirements"
created: 2026-08-06
updated: 2026-08-06
implemented: 2026-08-06
tags: [session, frontend, api]
document_role: primary
document_type: requirements
snapshot_id: session-260806
---

# Session Directory Requirements

- Snapshot: `session-260806`
- Document reference: `session-260806/REQ`

## Problem

An Agent's sidebar currently loads and renders every active session, and also loads every archived session in an expandable section. This does not remain usable or efficient as the session history grows, and users have no dedicated, paginated view of their complete session history.

## Primary Actor

An authenticated Workspace member who uses an Agent with many active and archived sessions.

## Primary Scenario

The member opens an Agent's session directory, switches between active and archived sessions, moves through pages of each list, and opens the chosen session. The Agent sidebar remains a compact navigation aid that exposes pinned sessions and at most 20 recently active sessions, with a route to the directory.

## Supporting Scenarios

- The member pins or unpins an active session and sees the sidebar and relevant directory list reflect the change.
- The member archives or restores a session and sees it leave or enter the appropriate directory list.
- The member opens the Agent on a narrow viewport and can reach the session directory from the mobile navigation.

## Goals

- Provide a dedicated, complete session directory for each Agent.
- Make active and archived session history scalable through pagination.
- Keep the Agent sidebar concise and useful for quick navigation.

## Non-Goals

- Change session ownership, authorization, archive retention, or automatic-archive policy.
- Show subagent sessions in ordinary Agent session lists.
- Add search, arbitrary sorting, bulk session actions, or session deletion.

## Requirements

### REQ-1. Paginated active session directory

A member can open a dedicated session directory for an Agent and browse all active root sessions in a paginated list.

**Acceptance criteria**

- The directory is reachable from the Agent navigation and has a stable URL.
- The active list contains only root sessions that are active and visible to the member.
- The member can move between available pages and open a listed session.
- The list preserves the existing user-facing active-session ordering unless a later confirmed requirement changes it.

### REQ-2. Paginated archived session directory

A member can switch the session directory to archived sessions and browse all archived root sessions in a separately paginated list.

**Acceptance criteria**

- Active and archived sessions are clearly distinguishable within the directory.
- The archived list contains only archived root sessions visible to the member.
- The member can move between available archived-list pages and open a listed session.
- Existing archive-retention information and restore behavior remain available where currently supported.

### REQ-3. Compact Agent sidebar

The Agent sidebar presents pinned active sessions and recent active sessions as a bounded quick-navigation list.

**Acceptance criteria**

- The sidebar shows every eligible pinned active root session.
- In addition to pinned sessions, the sidebar shows no more than 20 recently active root sessions.
- A session shown as pinned is not duplicated in the recent-session portion.
- The sidebar does not render an archived-session section or load archived sessions for sidebar display.
- The sidebar provides a visible route to the complete session directory.

### REQ-4. Coherent session-list updates

Session-list surfaces remain coherent after an action that changes a session's title, pinned state, active/archive status, or restore state.

**Acceptance criteria**

- A successful action updates or refreshes the affected sidebar and directory data without requiring a full browser reload.
- Archived sessions leave the active list on archive and return to it on restore; the archived list reflects the inverse transition.
- Existing restrictions on actions, including primary-session and running-session archive restrictions, remain enforced.

## Fixed Constraints

- Existing session authorization and root-session visibility rules remain authoritative.
- Existing direct session routes remain the navigation target for opening a session.
- Existing session pin semantics, including automatic-archive protection, remain unchanged.
- The sidebar limit is pinned sessions plus at most 20 recent active sessions; archived sessions are excluded.

## Open Assumptions

- The product will use the currently established active and archived ordering in the first release.
- The number of rows per directory page and the exact pagination control presentation are implementation details, provided pagination is understandable and accessible.
- Directory tabs or an equivalent control may express the active-versus-archived distinction.

## Confirmation

Confirmed by the requester on 2026-08-06 before ADR and design decisions began.
