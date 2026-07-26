---
title: "Unified Agent Input Mailbox Requirements"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, mailbox, engine]
document_role: primary
document_type: requirements
snapshot_id: mailbox-260726
---

# Unified Agent Input Mailbox Requirements

- Snapshot: `mailbox-260726`
- Document reference: `mailbox-260726/REQ`

## Problem

Agent-targeted input items originate from multiple product capabilities, and their producer-specific implementations do not expose one explicit canonical mailbox ownership boundary. These inputs include both messages and Turn Actions. An Agent coordinating subagents may also intentionally wait for a long-running descendant, but the current wait behavior reacts only to Agent-to-Agent mailbox messages. User messages, Turn Actions, External Channel invocations, and Goal continuations do not end the wait. A long wait can therefore delay inputs that should be delivered through the Agent's normal input path, while future input capabilities risk implementing storage and wake behavior independently.

## Primary Actor

A running Agent that is coordinating one or more active descendant agents.

## Primary Scenario

The Agent has at least one descendant that satisfies the existing subagent wait condition and calls the model-visible wait tool. If any supported pending mailbox item already exists, or one arrives while the tool is waiting, the tool returns without consuming the item. The Agent then receives and processes that input through the same existing ordered input path used when it is not waiting. A completed descendant's terminal result follows this same behavior because it is delivered as an Agent message.

## Supporting Scenarios

- A user sends a message while the Agent is waiting for a long-running descendant.
- An External Channel invocation reaches the Session while the Agent is waiting.
- A descendant sends an intermediate Agent message or completes and delivers its terminal result.
- A user Turn Action or Goal continuation becomes pending while the Agent is waiting.
- A pending mailbox item appears in Web history with reduced emphasis and transitions to its normal durable or active-execution presentation after it is read.
- Web refresh or live reconnection reconstructs the same pending mailbox-item presentation before the item is read.
- The Agent calls the wait tool when there is no descendant satisfying the existing wait condition.
- No qualifying input arrives before the requested timeout.

## Goals

- Establish one canonical mailbox storage boundary for every message or Turn Action whose target AgentSession and delivery eligibility have been resolved.
- Require every Agent input producer and the Agent loop to share that mailbox instead of maintaining producer-specific pending-delivery stores.
- Provide one shared pending-to-consumed Web presentation lifecycle for every mailbox item.
- Let one wait operation react to every item kind currently accepted by the mailbox.
- Preserve the existing delivery, ordering, promotion, and scheduling behavior of every input producer.
- Keep long subagent coordination waits responsive to user, External Channel, and other existing Session inputs.
- Present the capability to the model as a general `wait` tool with guidance that prevents indefinite waiting when no subagent work can complete.
- Keep the model-visible wait capability independent from the current descendant-only eligibility rule so later wait conditions can extend it without moving or replacing the tool.

## Non-Goals

- Interrupting or cancelling arbitrary long-running tools when input arrives.
- Starting an indefinite wait solely in anticipation of future user or External Channel input.
- Adding speculative input kinds that do not exist in the current Session input flow.
- Exposing additional wait eligibility conditions in this development snapshot.
- Changing whether an existing producer queues input or wakes an idle Session.
- Changing the content, ordering, or model-visible representation of accepted input.
- Moving raw External Channel webhook events, unauthorized messages, pending context, access requests, or routing state into the Agent mailbox before an AgentSession target and delivery eligibility are resolved.

## Requirements

### REQ-1. Store Agent-targeted input items in one canonical mailbox

Every message or Turn Action whose target AgentSession and delivery eligibility have been resolved must be stored through one shared mailbox persistence boundary, regardless of which product capability produced it.

**Acceptance criteria**

- User messages, Turn Actions, Agent messages, External Channel invocations, and Goal continuations create entries in the same canonical mailbox.
- The Agent loop discovers pending Agent input through the canonical mailbox rather than querying producer-specific message stores.
- A producer-specific domain record may retain source data and reference a mailbox entry, but it cannot be the sole pending-delivery representation after the item becomes eligible for an AgentSession.
- Source type, source identity, scheduling intent, idempotency identity, content, attachments, and other input-specific data required by existing behavior remain distinguishable through the shared mailbox contract.
- The mailbox persistence boundary has no wake, broker, Session-state, or notification side effects.
- Each producer remains responsible for confirming mailbox admission and then performing the Session wakeup or non-scheduling activity notification required by that producer's scheduling contract.
- Raw External Channel ingress and authorization or routing state remain outside the mailbox until the AgentSession target and delivery eligibility are resolved.
- Mailbox entries exist only while unread; the mailbox does not retain consumed entries or a consumed-item history.
- Pending observation by the wait tool, Web UI, or status queries does not read or delete a mailbox entry.
- The Agent input path deletes a message-like mailbox entry only when it successfully promotes the message into durable history.
- The Agent input path deletes an operation Turn Action mailbox entry only when it safely transfers ownership to its action-execution lifecycle.
- A failed promotion or ownership transfer leaves the mailbox entry available for retry rather than losing the input.

### REQ-2. Present every mailbox item through one pending-to-consumed UI lifecycle

Every mailbox item must be visible in Web history with reduced emphasis until the Agent input path reads it. A message-like item then transitions to its normal durable history presentation, while an operation Turn Action transitions to its normal active-execution presentation and later durable completion history.

**Acceptance criteria**

- Every mailbox item kind has a Web pending projection while its mailbox entry remains unread.
- The pending presentation preserves the source-specific message or action presentation while adding a common reduced-emphasis pending state.
- Successful message promotion deletes the mailbox entry, removes its pending projection, and displays the corresponding durable history item without producing a visible duplicate.
- Successful operation Turn Action handoff deletes the mailbox entry, removes its pending projection, and displays the corresponding action-execution state without producing a visible duplicate.
- Pending, action-execution, and durable representations retain stable correlation so ownership transitions do not reorder the conversation or briefly show the same logical item as unrelated duplicates.
- Refresh, history reload, and live reconnection reconstruct pending presentation from durable mailbox state rather than relying only on process-local or optimistic client state.
- External Channel messages receive a pending projection rather than remaining invisible until promotion.

### REQ-3. Preserve normal input delivery

Waiting must not create a separate delivery path or change how accepted Session input is ordered, promoted or handed off, represented, or processed.

**Acceptance criteria**

- Input received during a wait is processed through the same existing path as input received outside a wait.
- Ending a wait does not consume, delete, acknowledge, duplicate, or reorder the pending input.
- Existing producer-specific queue-only and Session-waking behavior remains unchanged.
- After confirming admission of a finalized External Channel invocation envelope, the External Channel producer retains its full Session-wakeup behavior: ensure the durable Session state is running and then send the broker signal after commit.
- The resulting signal must also make the admitted envelope observable to an eligible active `wait`; pre-admission context collection does not wake or notify the Agent.

### REQ-4. Retain the existing subagent wait condition

The tool may block only while the current Agent has descendant work that satisfies the existing `wait_agent` waiting condition.

**Acceptance criteria**

- If the current Agent has no descendants, the tool returns immediately with the existing no-descendant outcome.
- If descendants exist but none satisfies the existing active-descendant condition, the tool returns immediately with the existing all-idle outcome.
- The existence or possible future arrival of user or External Channel input does not by itself permit the tool to block.

### REQ-5. End waiting on any existing mailbox item

While the tool is allowed to wait, any pending item kind currently supported by the canonical mailbox must end the wait.

**Acceptance criteria**

- `USER_MESSAGE`, `ACTION_MESSAGE`, `AGENT_MESSAGE`, `EXTERNAL_CHANNEL_INVOCATION`, and `GOAL_CONTINUATION` each end an active wait.
- If any such input is already pending when the tool is called, the tool returns immediately.
- Input that commits concurrently with wait startup cannot be missed and cannot leave the tool blocked until timeout.
- Descendant idleness is not used as an independent successful completion path when the descendant's terminal result is being delivered through the normal Agent-message path.

### REQ-6. Preserve bounded wait timing

The generalized wait tool must retain the current timeout contract.

**Acceptance criteria**

- The default timeout remains 30 seconds.
- Callers may request a timeout from 0 through 600 seconds.
- A timeout returns a distinct timed-out outcome without consuming pending input.
- Immediate no-descendant, all-idle, or already-pending-input outcomes do not wait for the timeout.

### REQ-7. Expose the capability as `wait`

The model-visible tool must be named `wait` and must explain its relationship to descendant work and Session input activity.

**Acceptance criteria**

- `wait` replaces the current `wait_agent` model-visible tool name.
- The tool guidance states that it should be used when active descendant work makes waiting intentional.
- The guidance states that any normal mailbox input may end the wait and that the tool does not consume that input.
- The guidance does not encourage waiting solely for unbounded future user or External Channel input.
- The guidance communicates the 30-second default and 600-second maximum.

### REQ-8. Preserve descendant terminal delivery guarantees

A descendant completion must continue to reach its direct parent through the existing Agent-message input behavior and must be sufficient to end the parent's active wait.

**Acceptance criteria**

- Completed, failed, stopped, interrupted, and cancelled descendant results remain eligible for their existing direct-parent delivery behavior.
- The parent does not need a separate terminal-result observation path to end the wait.
- If atomic terminal finalization fails, recovery retries the complete terminal-state and parent-mailbox preparation rather than making `wait` repair delivery.
- Descendant terminal-result messages remain queue-only: they do not ensure the parent Session is running and do not send a full parent Session wakeup.
- A parent already blocked in `wait` can observe the committed queue-only terminal result through the live-owner activity path, while an idle parent remains idle until later Session-waking input arrives.

## Fixed Constraints

- The canonical mailbox begins only after a target AgentSession and delivery eligibility are resolved; pre-routing and pre-authorization provider ingress remains owned by its source domain.
- The initial mailbox item set is the current `InputBufferKind` set: user message, Turn Action, Agent message, External Channel invocation, and Goal continuation.
- Turn Actions remain typed actions with their existing action-specific processing and must not be flattened into ordinary message content.
- The mailbox owns unread accepted delivery state and deletes items when the Agent input path successfully reads and promotes them or safely transfers operation ownership; it retains no consumed-item state or history.
- The event transcript is the durable source of truth after successful message promotion, while live operation ownership belongs to the action-execution lifecycle until its durable terminal handoff.
- The existing active-descendant determination used by `wait_agent` remains the wait eligibility rule.
- Active descendant work is the only wait eligibility condition in this snapshot, but the tool ownership and runtime boundary must allow later conditions without relocating the model-visible `wait` tool or coupling generic wait infrastructure to the Subagent Toolkit.
- Existing input producer ownership and queue-only versus Session-waking scheduling semantics must remain stable.
- Mailbox persistence never initiates wake behavior. A Session wakeup means both ensuring durable running state and sending the broker signal; the producer owns that complete operation.
- A queue-only producer does not perform a Session wakeup, but it must emit a non-scheduling activity notification when needed to make the committed mailbox item observable to an already-active `wait`.
- External Channel invocation admission remains Session-waking, while unapproved or context-only External Channel messages outside the mailbox do not wake the Agent.
- Completed, failed, stopped, interrupted, and cancelled descendant terminal-result messages remain queue-only inputs for their direct parent.
- The feature must not broaden direct human write access to subagent Sessions.
- General tool interruption and stop handling remain separate from mailbox wait behavior.

## Open Assumptions

- The ADR must decide how one mailbox item correlates with one or more durable events or an intermediate action-execution projection while preserving one logical UI identity.
- The internal notification and observation mechanism will be selected during ADR discussion; the requirement is observable responsiveness without missed committed input, not a specific polling, broker, or in-process implementation.
- The exact structured return wording may be refined during design while preserving distinct mailbox-activity, no-descendant, all-idle, and timeout outcomes.

## Confirmation

Confirmed by the requester on 2026-07-26 before ADR and design decisions began.
