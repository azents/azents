---
title: "Private User Sessions"
created: 2026-08-06
tags: [session, privacy, memory, authorization, architecture]
document_role: primary
document_type: adr
snapshot_id: session-260806
---

# Private User Sessions

- Requirements: [session-260806/REQ](../requirements/session-260806-user-sessions.md)
- Document reference: `session-260806/ADR`

## Context

`session-260806/REQ` adds private User Sessions to an Agent without changing the existing Team Session product contract. A User Session is an independent, non-primary conversation associated with one durable User. Only that User may access it through product boundaries. It projects shared Agent Memory and its associated User's User Memory, while generic execution contexts remain Userless.

The existing Team Session execution-boundary ADR already fixes several relevant foundations: the root `AgentSession` owns a future User Session association; subagents derive it through root `SessionAgent` lineage; `session_kind` remains the root/subagent classifier; `primary_kind` remains a primary-conversation role; and only explicit User-owned capability resolution may consume the associated User. This ADR records only unresolved decisions required to implement the approved User Session requirements.

## Fixed and Derived Outcomes

- Team Sessions, including the Team primary Session, existing Team Session creation, Workspace-shared access, and External Channel routing remain unchanged.
- A User Session has no primary role and a User can create multiple User Sessions for one Agent.
- A User Session is private to its durable associated User. Workspace Owner, Manager, membership, direct identifiers, and Team participation do not independently grant access.
- Agent Memory remains shared by Agent. User Memory is available only to the User Session's durable associated User; other Users' User Memory remains unavailable.
- Broker wake-ups and generic Engine, Run, Worker, and ordinary Toolkit contexts remain Userless.
- User-brought Tools, personal credentials, External Channel DM routing, Session sharing/transfer, and filesystem-level Runtime isolation are outside this snapshot.

## Decision Topics

1. **Root User Session persistence and constraints**: how a root Session declares Team versus User product mode, stores its associated User, and prevents invalid root/subagent or Team/User combinations.
2. **Associated-User lifecycle**: what happens to a User Session and its private resources when the associated User loses Workspace membership or the User account is deleted.

Local implementation details, naming, query composition, route/module placement, generated-client mechanics, test fixture composition, and UI component structure are agent-owned unless they introduce a new product behavior or authority boundary.

## Decisions

### session-260806/ADR-D1. Store an explicit root Session product mode and associated User

Affected requirements: [session-260806/REQ-1](../requirements/session-260806-user-sessions.md#req-1-separate-team-and-user-session-navigation), [session-260806/REQ-2](../requirements/session-260806-user-sessions.md#req-2-create-independent-user-sessions-without-a-primary-role), [session-260806/REQ-3](../requirements/session-260806-user-sessions.md#req-3-enforce-complete-user-session-privacy-at-public-boundaries), and [session-260806/REQ-5](../requirements/session-260806-user-sessions.md#req-5-preserve-existing-team-session-behavior).

A root `AgentSession` stores an explicit product mode of Team or User. A root User Session stores one required durable associated User; a root Team Session stores no associated User. The persistence constraints reject an invalid root mode/associated-User combination. A subagent `AgentSession` stores neither product mode nor associated User and derives both through its root `SessionAgent` lineage. A User Session cannot receive a primary role; existing Team primary behavior remains valid only for a Team Session.

This makes Team/User classification explicit, prevents nullable ownership from becoming an implicit type discriminator, keeps User ownership in the conversation aggregate, and prevents duplicate mutable ownership across a subagent tree.

Rejected alternatives:

- Inferring the product mode solely from a nullable associated-User field would make a null value carry both absence and Team-type semantics, weakening constraints and future extension.
- A separate one-to-one User Session table would make the root Session's product identity indirect, complicate Session lookup/authorization, and diverge from the existing root `AgentSession` ownership boundary.

### session-260806/ADR-D2. Archive on membership loss and purge on User deletion

Affected requirements: [session-260806/REQ-2](../requirements/session-260806-user-sessions.md#req-2-create-independent-user-sessions-without-a-primary-role) and [session-260806/REQ-3](../requirements/session-260806-user-sessions.md#req-3-enforce-complete-user-session-privacy-at-public-boundaries).

When the associated User loses Workspace membership, public access to their User Sessions is denied immediately and each associated User Session in that Workspace is archived. The archived Session and its private resources remain retained. If the same User later regains Workspace membership, only that associated User may explicitly restore the archived User Session.

When the associated User account is deleted, the system purges each associated User Session and its User-Session-private resources through the established Session lifecycle. It does not retain an orphaned private Session without an associated User.

This immediately revokes access after membership loss without destructive loss of private work, keeps restoration explicit after rejoining, and gives account deletion a terminal owner-and-data boundary.

Rejected alternatives:

- Retaining active User Sessions after membership loss would leave inaccessible private work active and make restoration, background lifecycle, and ownership semantics ambiguous.
- Purging on membership loss would make an ordinary membership change destructively delete private work.
- Retaining an orphaned User Session after account deletion would violate the one durable associated-User invariant and create unclear future access authority.

### session-260806/ADR-D3. Use a durable owner-lifecycle workflow for membership loss and User deletion

Affected requirements: [session-260806/REQ-2](../requirements/session-260806-user-sessions.md#req-2-create-independent-user-sessions-without-a-primary-role) and [session-260806/REQ-3](../requirements/session-260806-user-sessions.md#req-3-enforce-complete-user-session-privacy-at-public-boundaries).

When a User loses Workspace membership, the membership removal takes effect immediately for authorization, and a durable owner-lifecycle operation archives that User's User Sessions after active Runs reach a safe stop/recovery boundary. When a User account is deleted, User access is disabled first and a durable owner-lifecycle operation purges the User's User Sessions and their private resources. The final User-row deletion is committed only after the purge workflow completes successfully.

The owner-lifecycle operation is retryable, observable, and reuses the existing Session archive/purge participant orchestration. It does not synchronously wait for Runtime, broker, object-storage, or active-Run cleanup inside the membership or account HTTP request, and it does not rely on database cascade to bypass Session lifecycle cleanup.

This preserves immediate privacy revocation, safe cleanup of active work and external resources, and a non-orphaned associated-User invariant.

Rejected alternatives:

- Synchronously waiting for all Session and resource cleanup would make membership/account requests depend on long-running external operations and would provide weak recovery after partial failure.
- Database cascade would bypass established Session lifecycle cleanup for broker state, object blobs, Runtime worktrees, and external participants.

## Decision Status

All material decisions for `session-260806` are accepted. Design may proceed.
