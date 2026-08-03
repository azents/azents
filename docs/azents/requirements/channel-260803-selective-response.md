---
title: "Selective External Channel Response Requirements"
created: 2026-08-03
updated: 2026-08-03
tags: [external-channel, agent, channel-work]
document_role: primary
document_type: requirements
snapshot_id: channel-260803
---

# Selective External Channel Response Requirements

- Snapshot: `channel-260803`
- Document reference: `channel-260803/REQ`

## Problem

An Agent processing an External Channel input currently has no way to complete Channel Work without publishing a reply. Channel conversations may include messages that are not addressed to the Agent or explicitly request no response, so mandatory publication can create unwanted interruptions. Silent completion must not discard unfinished Channel Work.

## Primary Actor

A root Agent processing an External Channel turn or continuation.

## Primary Scenario

An External Channel message is clearly not addressed to the Agent or explicitly asks the Agent not to respond. When the binding has no unfinished tasks, the Agent completes the associated Channel Work without publishing any provider message.

## Supporting Scenarios

- The Agent prefers responding when useful, especially when mentioned or directly instructed.
- An explicit request not to respond takes precedence even when the Agent is mentioned.
- When unfinished Channel Work exists, the Agent does not answer an unrelated message but preserves and continues the existing work.
- An ordinary chat user's explicit request to publish externally cannot be silently ignored.
- Existing Channel Work remains available across AgentRun boundaries, Worker restart or ownership handoff, and Session archive and restore.

## Goals

- Allow an Agent to complete eligible Channel Work without publishing a reply.
- Prefer useful participation while avoiding replies to messages clearly unrelated to the Agent.
- Preserve all unfinished Channel Work.
- Consolidate Channel Work into the existing session-bound Toolkit State authority.

## Non-Goals

- Changing External Channel message admission, routing, or response-mode eligibility.
- Discarding or silently completing unfinished tasks.
- Allowing ordinary chat publication requests to be silently ignored.
- Adding provider-specific behavior or another persistence mechanism.
- Retaining a dedicated or fallback Channel Work source of truth after cutover.

## Requirements

### REQ-1. Selective response judgment

The Agent must treat External Channel messages as conversational context that may not contain instructions for the Agent. It must generally prefer a useful response, prioritize responding when mentioned or directly instructed, and choose no response only when the message is clearly not addressed to it or explicitly asks it not to respond.

**Acceptance criteria**

- A mention or direct instruction normally results in a response.
- A message clearly addressed to other participants may result in no response.
- An explicit request not to respond takes precedence over a mention.
- Uncertain cases prefer responding rather than silent completion.

### REQ-2. Silent Channel Work completion

When the Agent chooses no response and the current Channel Work has no unfinished tasks, it must complete the Channel Work without publishing any provider content.

**Acceptance criteria**

- No conversational reply, progress update, file, or other provider effect is produced.
- The Channel Work becomes finished and is no longer eligible for idle continuation.
- Channel Work with no tasks is eligible for silent completion.
- Channel Work whose tasks are all `completed` or `failed` is eligible for silent completion.

### REQ-3. Unfinished work preservation

Channel Work containing at least one `pending` or `in_progress` task must not be silently completed.

**Acceptance criteria**

- An attempt to silently complete such Channel Work is rejected before provider or Channel Work mutation.
- The Channel Work remains active with its existing task state intact.
- The Agent may leave the unrelated current message unanswered while continuing the existing work.

### REQ-4. External-input scope

Silent completion must be available only while processing an External Channel turn or continuation.

**Acceptance criteria**

- An ordinary chat user's explicit external-publication request cannot use silent completion.
- Existing explicit publication behavior from ordinary chat remains unchanged.

### REQ-5. Session-bound Channel Work ownership

Channel Work and its current provider projection must use the existing session-bound Toolkit State as their single canonical source of truth.

**Acceptance criteria**

- Channel Work title, ordered tasks, lifecycle status, revisions, desired progress, and current provider projection are represented by one versioned typed Toolkit State contract.
- Independent bindings retain independent Channel Work within the same AgentSession.
- Active Channel Work survives AgentRun boundaries, Worker restart or ownership handoff, and Session archive and restore.
- Idle continuation, compaction continuity, Session Channels management, lifecycle cleanup, and provider-effect revision checks observe the same canonical Toolkit State.
- Existing active Channel Work and current provider projection remain intact when the new ownership model is deployed.
- Dedicated Channel Work and projection storage is removed after cutover without dual-read, dual-write, fallback, or a second source of truth.

## Fixed Constraints

- Existing External Channel admission, routing, response modes, provider delivery, and task status semantics remain unchanged.
- The capability introduces no new persistence mechanism and reuses the existing session-bound `toolkit_states` store.
- Channel Work uses one Toolkit State source of truth rather than dedicated Work or projection tables.
- Normal assistant output remains unavailable as an External Channel publication path.
- The cutover must preserve existing observable Channel Work, Activity Tracker, management, continuation, archive, restore, and purge behavior except for the new selective-response capability.
- Implementation changes must remain limited to the Channel Work source-of-truth cutover and the new selective-response behavior.

## Open Assumptions

- The External Channel input provides enough conversational context for the Agent to judge whether a message is directed to it.

## Confirmation

Reconfirmed by the requester on 2026-08-03 after adding the session-bound Toolkit State ownership and cutover scope.
