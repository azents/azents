---
title: "Session Folder Project Browser Prominence Requirements"
created: 2026-08-04
updated: 2026-08-04
implemented: 2026-08-04
tags: [session, workspace, project-browser, frontend]
document_role: primary
document_type: requirements
snapshot_id: session-260804
---

# Session Folder Project Browser Prominence Requirements

- Snapshot: `session-260804`
- Document reference: `session-260804/REQ`

## Problem

The Projects browser already includes the current Session folder, but ordinary directory-name sorting can place it below registered Projects. Its row also omits the working-folder path that is shown for registered Project roots. Users cannot immediately identify the Session-owned working location or distinguish its exact filesystem boundary from other Projects.

## Primary Actor

A workspace member reviewing files and Projects for an active root Session.

## Primary Scenario

The member opens the Projects browser in an active Session. The Session files entry is the first root entry, and the member can read its current Session working-folder path directly from the row before opening or managing its contents.

## Supporting Scenarios

- The Session has one or more registered Projects or Azents-created Git worktrees.
- The Session folder is visible before its physical directory has been materialized.
- The Projects browser is viewed in a narrow mobile viewport.
- The user refreshes the Project browser or Project status projections change.

## Goals

- Make the Session-owned working location the first identifiable Project-browser entry.
- Show the Session working-folder path using the same Project-root row information hierarchy as registered Projects.
- Preserve clear path identification on narrow viewports without hiding the Session files name.

## Non-Goals

- Changing Session-folder lifecycle, cleanup, access, or filesystem-operation authority.
- Changing registered Project or Git-worktree ordering relative to one another.
- Changing All files mode, its Agent Workspace root, or its directory ordering.
- Adding a new persisted field or public API field for the Session-folder path.
- Keeping an unmatched Session files entry visible when a Project-browser search filters it out.

## Requirements

### REQ-1. Session files is the first Projects root entry

The current Session files entry must be displayed before every registered Project and Git worktree root in the Projects browser whenever it is included in the displayed root list.

**Acceptance criteria**

- An unfiltered Projects browser displays Session files as its first root entry when the Session manifest includes it.
- The ordering remains true after manifest refresh and Project status refresh.
- Registered Projects and Git worktrees keep their existing relative ordering behavior after the Session files entry.
- All files mode retains its existing directory ordering behavior.

### REQ-2. Session working-folder path is visible in its row

The Session files root row must display the exact current Session working-folder path as supporting information alongside its name.

**Acceptance criteria**

- The displayed path equals the path supplied for the Session files browser entry.
- The Session files name remains visible when horizontal space is constrained.
- A narrow viewport may truncate the visible path with an ellipsis, while the full exact path remains available through the row's existing full-path affordance.
- Registered Project root path display remains unchanged.

## Fixed Constraints

- The Session-folder path remains derived from current Runner-reported Agent Workspace evidence and the persisted Session context; no frontend path construction or fallback path is introduced.
- The existing implemented `session-260803` Requirements, ADR, and Design remain immutable historical records.
- The Project Browser manifest remains the server-owned source of entry identity, path, source type, status, and capabilities.
- Git-tracked documentation and source code remain in English.

## Open Assumptions

- The current Project-browser search behavior continues to filter root entries by the user query rather than pinning unmatched entries.
- The current row title behavior is sufficient as the full-path affordance for truncated paths without adding a mobile-only interaction.

## Confirmation

Confirmed by the requester on 2026-08-04 before ADR and design decisions began.
