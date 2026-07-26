---
title: "Session Auto-Archive Requirements"
created: 2026-07-26
updated: 2026-07-26
implemented: 2026-07-26
tags: [session, agent, lifecycle]
document_role: primary
document_type: requirements
snapshot_id: session-260726
---

# Session Auto-Archive Requirements

- Snapshot: `session-260726`
- Document reference: `session-260726/REQ`

## Problem

Users need inactive conversation sessions to leave the active session list without
requiring manual cleanup, while retaining an explicit way to preserve sessions they
consider important.

## Primary Actor

A Workspace user who manages and uses an Agent's sessions.

## Primary Scenario

A user leaves a non-pinned session without any user, Agent, or tool activity for the
Agent's configured inactivity period. The session is automatically archived and is
subsequently represented exactly as a manually archived session. The user can pin a
session from the session-list overflow menu before that period ends so it remains
active and visibly marked as pinned.

## Supporting Scenarios

- A user opens an Agent's settings and sees a default automatic archive inactivity
  period of 30 days, then changes that Agent's period.
- A user pins or unpins an active session from the session-list overflow menu; the
  list immediately reflects its pinned state.
- A pinned session remains outside automatic archive eligibility even after the
  configured inactivity period elapses.

## Goals

- Keep active session lists focused on recently active work.
- Let users preserve important active sessions explicitly.
- Keep automatic and manual archiving behavior consistent.

## Non-Goals

- Deleting archived sessions or changing existing archived-session retention and
  purge behavior.
- Adding a notification when an automatic archive occurs.
- Adding TTL disablement, TTL range policy, or workspace-wide automatic archive
  policy beyond the requested per-Agent setting.
- Changing the behavior of manual archive or restore.

## Requirements

### REQ-1. Per-Agent automatic archive period

Users can view and set an automatic archive inactivity period for each Agent. A new
or otherwise unset Agent uses 30 days as the default period.

**Acceptance criteria**

- An Agent settings surface exposes the automatic archive inactivity period.
- A newly created Agent, and an existing Agent without an explicit value, displays
  and uses a 30-day period.
- Changing one Agent's period does not change another Agent's period.

### REQ-2. Inactivity-based automatic archive

A non-pinned active session is automatically archived after its owning Agent's
configured inactivity period has elapsed without session activity.

**Acceptance criteria**

- The inactivity calculation accounts for user messages, Agent messages, and tool
  executions as session activity.
- A session with activity during its inactivity period remains active until a full
  configured period has elapsed since its latest activity.
- An eligible session is no longer shown as active after automatic archive.

### REQ-3. Automatic archive equivalence

Automatic archive produces the same user-visible session outcome as a user manually
archiving that session.

**Acceptance criteria**

- An automatically archived session has the same archive state and availability in
  the archived-session experience as a manually archived session.
- Automatic archive observes the same eligibility restrictions and lifecycle effects
  as manual archive.

### REQ-4. Session pinning

Users can pin and unpin an active session from its session-list overflow menu.

**Acceptance criteria**

- The session-list overflow menu offers the appropriate Pin or Unpin action for an
  active session.
- A pinned session has a visible pinned indicator in the session list.
- Pinning and unpinning are reflected without requiring the user to reload the page.

### REQ-5. Pinned-session protection

Pinned active sessions are excluded from automatic archive eligibility.

**Acceptance criteria**

- A pinned session remains active when its inactivity period elapses.
- After a session is unpinned, automatic archive eligibility is evaluated using its
  current inactivity history and the owning Agent's configured period.
- Pinning does not prevent a user from manually archiving the session when manual
  archive is otherwise allowed.

## Fixed Constraints

- Automatic archive is functionally identical to manual archive.
- Session activity includes user messages, Agent messages, and tool executions.
- Automatic archive configuration is scoped to an Agent.
- The default automatic archive inactivity period is 30 days.
- Pinned sessions are excluded only from automatic archive; manual archive behavior
  remains unchanged.

## Open Assumptions

- The existing archive eligibility rules determine whether an inactive session may
  be automatically archived; this feature does not introduce exceptions to them.
- The requested scope does not include a setting that disables automatic archive.

## Confirmation

Confirmed by the requester on 2026-07-26 before ADR and design decisions began.
