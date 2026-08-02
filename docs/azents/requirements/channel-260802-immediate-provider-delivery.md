---
title: "Immediate External Channel Provider Delivery Requirements"
created: 2026-08-02
updated: 2026-08-02
tags: [external-channel, slack, discord, delivery]
document_role: primary
document_type: requirements
snapshot_id: channel-260802
---

# Immediate External Channel Provider Delivery Requirements

- Snapshot: `channel-260802`
- Document reference: `channel-260802/REQ`

## Problem

External Channel publication currently creates dedicated Channel Action and provider-delivery history in addition to the ordinary Session tool-call history. This duplicates the accepted request and result, introduces External-Channel-specific replay and recovery behavior, and exposes internal provider operations as a separate management history.

External Channel publication must instead behave like an ordinary Tool call. The Session history must remain the execution history, while Slack and Discord provider effects execute directly without a separate durable delivery workflow.

## Primary Actor

A participant whose Slack or Discord request is being handled by an Azents Agent.

## Primary Scenario

A participant sends a request through a connected Slack or Discord conversation. The Agent invokes `channel_action`. Azents performs the requested provider operation during that Tool execution, waits for the immediate provider outcome, and records the Tool call and result through the normal Session history. No separate Channel Action or delivery-attempt history, pending work item, retry, replay, or recovery record is created.

## Supporting Scenarios

- The Agent publishes a text reply, a file-bearing reply, or a Channel Work progress change through the same ordinary Tool execution behavior.
- Setup, access, presence, settings, initial-progress, disconnect, and cleanup controls execute as direct best-effort provider effects without their own history or recovery workflow.
- Existing dedicated Channel Action and delivery-attempt data is deleted without being copied into Session history or another replacement ledger.

## Goals

- Make External Channel publication follow the normal Session Tool call and result lifecycle.
- Use Session history as the sole durable history of Agent-requested External Channel actions and their immediate results.
- Remove dedicated provider-delivery queues, attempt histories, recovery loops, and management history.
- Preserve current External Channel replies, files, Channel Work, authorization, and provider targeting behavior unless this snapshot explicitly changes it.

## Non-Goals

- Guarantee provider delivery across process termination or infrastructure interruption.
- Automatically retry, replay, compensate, or reconstruct an interrupted provider mutation.
- Backfill historical Channel Action or delivery-attempt data into Session history.
- Introduce a replacement outbox, queue, audit table, or compatibility fallback.
- Change the participant-facing content, Channel Work task model, binding model, or provider selection behavior.

## Requirements

### REQ-1. Ordinary Tool execution

Agent-requested External Channel publication must execute as an ordinary Tool call and wait for its immediate provider outcome.

**Acceptance criteria**

- A `channel_action` invocation performs the requested Slack or Discord operation before the Tool execution returns.
- The corresponding Tool call and Tool result are recorded through the normal Session history path.
- External Channel publication has no separate acceptance, completion, compensation, retry, replay, or recovery lifecycle.
- Provider-specific behavior does not change the normal Tool execution policy.

### REQ-2. Single execution-history authority

Session history must be the only durable history of Agent-requested External Channel Tool execution.

**Acceptance criteria**

- The Tool input is not duplicated into a dedicated Channel Action history.
- The provider outcome is not duplicated into a dedicated delivery-attempt history.
- Session management does not expose a separate list of provider delivery attempts or outcomes.
- Existing dedicated Channel Action and delivery-attempt records are deleted without archive, export, or Session-history backfill.

### REQ-3. Uniform direct provider effects

All External Channel provider effects outside Agent Tool execution must follow the same record-free direct-execution policy.

**Acceptance criteria**

- Setup, access, presence, settings, initial-progress, disconnect, and cleanup controls do not create persistent delivery work or outcome records.
- These controls do not create synthetic Session-history events.
- Their provider outcomes do not gate canonical mailbox admission, Session wake, or AgentRun creation.
- Failed or interrupted controls are not recovered or automatically retried by a background process.

### REQ-4. Current domain state remains authoritative

Removing action and delivery histories must not remove the current External Channel domain state required for ongoing behavior.

**Acceptance criteria**

- Current binding, resource, connection, authorization, Channel Work, and provider projection identities remain available where required by their existing behavior.
- Current Channel Work state is not reconstructed from historical Tool calls or provider delivery attempts.
- Provider failure does not trigger External-Channel-specific rollback or compensation of otherwise valid Tool-side domain changes.
- No current projection state retains a reference to a removed action or delivery-attempt record.

### REQ-5. Immediate failure and ambiguity reporting

Agent-requested publication must expose the immediate provider result through the normal Tool result without creating a separate durable delivery result.

**Acceptance criteria**

- Confirmed provider rejection is returned as a failed Tool result or equivalent structured Tool outcome.
- An ambiguous provider result is reported as unknown without automatic replay.
- A process interruption may leave the Provider operation omitted or ambiguous; startup and background workers do not reconstruct or execute it.
- Non-Tool control failures remain limited to normal operational logs and metrics.

### REQ-6. Direct file publication

File-bearing External Channel publication must use the same immediate, record-free Tool execution model.

**Acceptance criteria**

- Runtime and Exchange file sources are authorized and streamed during the current Tool execution.
- Pre-provider validation failure is returned through the current Tool result.
- Provider mutation is not replayed after it starts or becomes ambiguous.
- Interrupted Runtime transfer claims expire or clean up through their existing bounded lifecycle without a persistent External Channel delivery recovery record.

### REQ-7. Complete legacy workflow removal

The dedicated Channel Action and delivery-attempt workflow must be removed as one complete product behavior.

**Acceptance criteria**

- No dedicated persistent Channel Action or provider delivery-attempt records remain after migration.
- No Worker, scheduler, API, UI, lifecycle finalizer, or provider adapter consumes those removed records.
- No generated client exposes the removed management delivery-history contract.
- No compatibility fallback or second delivery authority remains reachable.

## Fixed Constraints

- Existing executed migrations remain immutable; schema removal uses a new migration.
- Provider credentials, payloads, raw identifiers, file bytes, and sensitive URLs remain excluded from logs and operational evidence.
- Canonical mailbox admission, Session wake, and AgentRun creation remain independent from provider-control success.
- Ambiguous provider mutations are not blindly replayed.
- Existing External Channel authorization and Runtime file-authority checks remain enforced at the direct provider boundary.
- Historical action and delivery data is deleted rather than retained or transformed.

## Open Assumptions

- Immediate provider responses are sufficient for the current Tool result when the process remains alive.
- Current provider projection identity is domain state, not delivery history, and may remain where required for later update or deletion.
- Existing Session history already contains the durable Tool calls and results that remain useful after legacy records are deleted.

## Confirmation

Confirmed by the requester on 2026-08-02 before ADR and design decisions began.
