---
title: "Discord Quiet Work Presence Requirements"
created: 2026-08-28
updated: 2026-08-28
implemented: 2026-08-28
tags: [discord, external-channel, activity, product]
document_role: primary
document_type: requirements
snapshot_id: discord-260828
---

# Discord Quiet Work Presence Requirements

- Snapshot: `discord-260828`
- Document reference: `discord-260828/REQ`

## Problem

Discord participants currently receive an Activity Tracker whenever conversational
Channel Work begins, including work triggered by an unmentioned message in a
conversation configured to respond to all messages. Repeated Tracker messages make a
busy Discord channel visually noisy even when participants only need a lightweight
signal that the Agent is working.

## Primary Actor

A Discord participant communicating with an Agent in an already connected Discord
conversation.

## Primary Scenario

A participant sends an eligible unmentioned message in a Discord conversation whose
response mode admits all messages. The Agent begins Channel Work and Discord shows the
Agent as typing without publishing an Activity Tracker. While that same Work remains
active, a participant explicitly mentions the Agent; Discord then shows one Activity
Tracker containing the latest available Work progress. When the Work finishes, is
silently completed, or loses its connected conversation, the typing presence ends.

## Supporting Scenarios

- An explicit mention starts new conversational Channel Work, so typing and one
  Activity Tracker are both visible from the beginning.
- Agent Worker or Discord Gateway Worker restarts do not permanently lose the desired
  typing or Tracker visibility for still-active Work.
- Repeated mentions during one Work cycle do not create duplicate Activity Trackers.
- Provider outages or reconnect periods may temporarily interrupt typing without
  changing the canonical Work lifecycle.

## Goals

- Replace unnecessary conversational Activity Tracker messages with lightweight
  Discord typing presence.
- Preserve detailed progress visibility when a participant explicitly mentions the
  Agent.
- Keep typing and Tracker behavior aligned with the durable Channel Work lifecycle
  across continuation, completion, disconnection, and worker restart.

## Non-Goals

- Changing which Discord messages invoke an Agent or create Channel Work.
- Changing Discord conversation response modes, routing, authorization, or Session
  ownership.
- Changing Slack Activity Tracker behavior.
- Changing Scheduled Task-owned Discord Activity Trackers, which remain visible without
  a participant mention requirement.
- Using Discord typing presence as execution, delivery, or recovery authority.
- Guaranteeing an instantaneous visual typing stop beyond Discord's provider contract.

## Requirements

### REQ-1. Typing for admitted conversational Work

Every Discord conversational input that would currently create or reactivate Channel
Work and its initial Activity Tracker must instead activate Discord typing presence for
the Work's delivery conversation, regardless of whether the input explicitly mentions
the Agent.

**Acceptance criteria**

- An eligible explicit mention activates typing.
- An eligible unmentioned message admitted by an existing all-messages Binding
  activates typing.
- Messages that do not create or reactivate conversational Channel Work do not activate
  typing under this feature.

### REQ-2. Active-Work typing lifecycle

Typing presence must remain desired while the corresponding Channel Work is active and
must cease being renewed when that Work finishes, is silently completed, the Binding
terminates, or the provider connection can no longer serve the conversation.

**Acceptance criteria**

- Intermediate replies and progress changes do not stop typing while Work remains
  active.
- `finish`, `ignore`, and Binding termination stop further typing renewal.
- A finished Work is not restored as typing after a worker restart.
- Provider-defined indicator expiry may delay the final visual disappearance after
  renewal stops.

### REQ-3. Mention-gated Activity Tracker

A Discord conversational Activity Tracker must be visible for a Work cycle only after
an eligible explicit invocation mentions the connected Agent during that cycle.

**Acceptance criteria**

- Work started by an unmentioned all-messages input publishes no Activity Tracker.
- Work started by an explicit mention publishes one Activity Tracker.
- Progress title or task changes do not publish a hidden Tracker without a qualifying
  mention.
- Slack presentation is unchanged.

### REQ-4. Late mention promotion

If an eligible explicit mention arrives while a Tracker-hidden Work cycle remains
active, that cycle must become Tracker-visible and publish its latest complete progress
snapshot once.

**Acceptance criteria**

- The newly visible Tracker reflects the latest canonical Work title and ordered tasks,
  not only the initial checking state.
- Repeated or concurrent qualifying mentions converge on one Tracker identity for the
  Work cycle.
- Later progress updates continue updating that same Tracker through the existing
  lifecycle.

### REQ-5. Restart recovery

Desired typing and Tracker visibility must survive Agent Worker and Discord Gateway
Worker restarts through existing durable Channel Work authority.

**Acceptance criteria**

- Restarting an Agent Worker does not finish active Work or hide an already-visible
  Tracker.
- After a Discord Gateway Worker reconnects, typing resumes for still-active eligible
  Work without requiring a new participant message.
- Work finished while the Gateway Worker was unavailable does not resume typing after
  reconnect.
- A qualifying mention durably admitted while the Gateway Worker was unavailable can
  still make the active Work Tracker-visible.

### REQ-6. Provider failure isolation

Discord typing failures or temporary absence must not roll back, finish, duplicate, or
otherwise redefine canonical Channel Work, mailbox input, Agent execution, replies, or
Activity Tracker state.

**Acceptance criteria**

- Typing transport failure leaves canonical Work active and recoverable.
- Recovery does not replay participant input or duplicate an Activity Tracker.
- Provider health and typing diagnostics expose no message content or credentials.

## Fixed Constraints

- Discord typing indicators expire after the provider-defined interval unless renewed,
  and Discord exposes no explicit typing-stop operation.
- PostgreSQL-backed canonical Channel Work remains the correctness and restart-recovery
  authority; Redis and process-local tasks are optional wake or presentation
  mechanisms only.
- Discord provider operations use the pinned supported SDK boundary and must not add a
  second Discord SDK or an unapproved direct provider transport.
- Existing Channel Work, Binding, Session, routing, authorization, and provider-delivery
  ownership boundaries remain authoritative.

## Open Assumptions

- None.

## Confirmation

Confirmed by the requester on 2026-08-28 before ADR and Design decisions began. The
requester also confirmed that Scheduled Task-owned Discord Activity Trackers remain
unchanged.
