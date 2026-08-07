---
title: "New Session Scope Selection and Pinned Directory Order Requirements"
created: 2026-08-07
updated: 2026-08-07
implemented: 2026-08-07
tags: [session, frontend, directory]
document_role: primary
document_type: requirements
snapshot_id: session-260807
---

# New Session Scope Selection and Pinned Directory Order Requirements

- Snapshot: `session-260807`
- Document reference: `session-260807/REQ`

## Problem

A member can create either a Team Session or a private User Session, but the new-session page does not let the member make that choice in the page itself. Separately, the complete Team session directory exposes pinned state but does not prioritize pinned sessions, making intentionally retained work less discoverable than recently active unpinned work.

## Primary Actor

An authenticated Workspace member starting a new session for an Agent.

## Primary Scenario

The member opens an Agent's new-session page, sees Team selected by default, chooses Team or User before sending the first message, and starts a session in the chosen scope. The member can later open the Agent's active Team session directory and find the Team primary session first, followed by pinned sessions before other active Team sessions.

## Supporting Scenarios

- A member leaves the default Team choice unchanged and starts a Team Session with the existing creation behavior.
- A member changes the choice to User and starts a private User Session that remains subject to the established requester-ownership boundary.
- A member pins or unpins an active Team session and sees the active directory reorder without a browser reload.
- A member opens archived Team sessions; their existing archive-time order remains unchanged.

## Goals

- Let members deliberately choose the Team or User scope before creating a session.
- Make pinned active Team sessions easier to find in the complete Team session directory.
- Preserve the established Team primary, Team/User ownership, archive, and sidebar semantics.

## Non-Goals

- Changing Team Session sharing, User Session ownership, authorization, or direct-session access rules.
- Adding a User Session directory, changing User Session list behavior, or changing User Session pin semantics.
- Changing the bounded sidebar pinned/recent projection or its ordering.
- Adding arbitrary sorting controls, search, bulk actions, or new session persistence before the first accepted message.
- Changing archived Team session ordering.

## Requirements

### REQ-1. Explicit new-session scope selection

A member must be able to choose whether an Agent's new session starts as a Team Session or a User Session before the first message is sent.

**Acceptance criteria**

- Opening the new-session page presents Team and User as clear scope choices, with Team selected by default.
- The member can change the selection before sending the first message.
- The first accepted message creates a session in the selected scope.
- Leaving the default selection unchanged preserves the existing Team Session creation behavior.
- Choosing User preserves the established requester-owned User Session visibility and access behavior.
- The page does not create a durable session solely because the member changes the scope selection.

### REQ-2. Pinned-first active Team directory ordering

The active Team session directory must prioritize intentionally pinned sessions while preserving the Team primary session's established leading position.

**Acceptance criteria**

- The Team primary session remains first when it is present.
- All other pinned active Team root sessions appear immediately after the Team primary session.
- Remaining active Team root sessions appear after pinned sessions in the established recency order.
- Pinning or unpinning an active Team session refreshes the directory so the row moves to its correct position without a full browser reload.
- Pagination reflects the same ordering across pages with deterministic placement for equal recency values.
- Archived Team session ordering remains unchanged.

## Fixed Constraints

- Team Sessions remain Workspace-shared and User Sessions remain visible only to their associated requester under the existing authorization model.
- The Team primary session remains unpinnable and retains its first-row position.
- The complete directory continues to list Team root sessions only; User Sessions remain outside Team directory endpoints.
- Existing active-session recency ordering remains the tie-breaking order within the pinned and unpinned groups.
- Existing sidebar pinned and recent projections remain authoritative for the sidebar.

## Open Assumptions

- The selector's local presentation and accessible control type are implementation details, provided both scopes and the current selection are clear before the first message.
- Existing route query state may continue to represent the selected scope if it remains consistent with the page interaction and direct navigation.

## Confirmation

Confirmed by the requester on 2026-08-07 through the direct instruction to implement
the specified scope and ordering.
