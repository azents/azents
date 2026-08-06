---
title: "Private User Sessions Requirements"
created: 2026-08-06
updated: 2026-08-06
tags: [session, privacy, memory, frontend, authorization]
document_role: primary
document_type: requirements
snapshot_id: session-260806
---

# Private User Sessions Requirements

- Snapshot: `session-260806`
- Document reference: `session-260806/REQ`

## Problem

All currently implemented Agent Sessions are Team Sessions: Workspace members who can access an Agent can access its Team conversations. A Workspace member cannot keep an Agent conversation, its transcript, and its personal memory context private from other members while still using the same Agent and its shared knowledge.

## Primary Actor

A Workspace member using an Agent for an individual, private conversation.

## Primary Scenario

A Workspace member opens the Agent session list, selects the My Sessions tab, and starts a new private-session draft. The first message creates a User Session associated with that member and opens its concrete conversation. The Agent can use shared Agent Memory and that member's User Memory. Other Workspace members cannot discover, read, subscribe to, control, or download resources from the User Session.

## Supporting Scenarios

- The associated User views and reopens any of their User Sessions from My Sessions; User Sessions have no primary Session.
- A different Workspace member attempts to access a User Session through a list, direct URL, history, live subscription, mutation, control, subagent-tree, or resource-download boundary and is denied without learning private Session content.
- The member switches between Team Sessions and My Sessions through separate session-list tabs. Existing Team Session behavior, including the Team primary Session and External Channel routing, remains unchanged.
- A User Session can use shared Agent Memory without accessing another User's User Memory.

## Goals

- Let a Workspace member create and use multiple private User Sessions under an existing Agent.
- Keep every User Session visible and usable only by its durable associated User.
- Keep User Sessions out of Team Session discovery and preserve the current Team Session product contract.
- Make both shared Agent Memory and the associated User's User Memory available in a User Session.
- Give Team Sessions and User Sessions distinct, understandable navigation through session-list tabs.

## Non-Goals

- Changing Team Session visibility, Team primary behavior, Team Session creation, or External Channel routing.
- Giving Workspace Owners, Managers, or other members implicit access to a User Session.
- Adding a User Session primary role, automatic per-user default Session, or default User Session routing.
- Adding User-brought Tools, personal OAuth credentials, or other personal credential capabilities.
- Routing Slack, Discord, or other External Channel direct messages to User Sessions.
- Providing filesystem-level isolation inside the shared Agent Runtime or Agent Workspace.
- Sharing, transferring, or delegating access to a User Session.

## Requirements

### REQ-1. Separate Team and User Session navigation

An Agent session list must present Team Sessions and the current requester's User Sessions in separate tabs.

**Acceptance criteria**

- The Team Sessions tab continues to present the existing Team Session list and behavior.
- The My Sessions tab lists only active User Sessions associated with the current requester for the selected Agent.
- A User Session is never included in another member's My Sessions tab or in the Team Sessions tab.
- Each tab's create affordance creates only its corresponding Session type.

### REQ-2. Create independent User Sessions without a primary role

A Workspace member must be able to start a private-session draft from My Sessions, and the first message must create one independent User Session associated with that member.

**Acceptance criteria**

- Opening a private-session draft does not create a durable Session before the first message is accepted.
- The accepted first message creates exactly one User Session and stores it as associated with the current requester.
- The UI navigates to the created concrete User Session after the first-message response succeeds.
- A User may have multiple User Sessions for the same Agent.
- No User Session has a primary role or is automatically selected as a per-user default Session.

### REQ-3. Enforce complete User Session privacy at public boundaries

Only the User durably associated with a User Session may access that Session through user-facing product boundaries.

**Acceptance criteria**

- The associated User can list, view, subscribe to, submit input to, mutate, control, archive, restore, inspect the subagent tree of, and download authorized resources from their User Session, subject to the existing Agent and Workspace access prerequisites.
- A different Workspace member, including an Owner or Manager, cannot list, view, subscribe to, submit input to, mutate, control, inspect, or download User Session resources.
- A denied request does not disclose the User Session title, transcript, participants, files, run state, or other private content.
- Direct identifiers, prior participation in a Team Session, and Workspace role do not grant User Session access.
- Team Session access remains governed by its existing Workspace-shared rules.

### REQ-4. Provide scoped Memory in User Sessions

A User Session must provide shared Agent Memory and the associated User's User Memory while preserving Memory isolation.

**Acceptance criteria**

- A User Session can read, search, create, update, and delete its Agent's shared Agent Memory according to the existing Agent Memory behavior.
- A User Session can read, search, create, update, and delete only User Memory associated with its durable associated User and Agent.
- A User Session cannot access User Memory associated with any other User.
- Team Sessions continue to expose Agent Memory only and cannot access User Memory.
- Personal Memory access does not depend on the latest message sender, current viewer, wake-up source, or another fallback identity.

### REQ-5. Preserve existing Team Session behavior

Adding User Sessions must not change the current Team Session product contract.

**Acceptance criteria**

- The existing Team primary Session remains the Team default conversation.
- Existing Team Session lists, creation flow, Workspace-shared authorization, and External Channel routing retain their current behavior.
- Team Session execution remains independent of User identity and uses Agent Memory only.
- A User Session does not become an implicit destination for Team, External Channel, scheduled, recovery, continuation, or subagent work.

## Fixed Constraints

- A User Session is a private conversation associated with one durable User; it has no primary role.
- The associated User is distinct from a current requester, message sender, viewer, or internal execution identity.
- The current requester must satisfy existing authenticated Agent and Workspace access prerequisites in addition to User Session ownership.
- Generic Engine, Run, Worker, and ordinary Toolkit execution contexts remain Userless. Only explicitly User-owned capabilities may consume a User Session's associated User.
- The first User-owned capability is User Memory. Shared Agent Memory remains available in both Session types.
- Team Sessions remain unchanged by this snapshot.
- Git-tracked artifacts and operator-facing errors remain in English.

## Open Assumptions

- When the associated User loses Workspace membership or the User account is deleted, later work will define retention, archival, and purge behavior for the existing User Session and its private resources. Until that later decision, existing authenticated Agent and Workspace access prerequisites continue to govern user-facing access.

## Confirmation

The requester confirmed this complete Requirements snapshot on 2026-08-06 before ADR and Design decisions began.
