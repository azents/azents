---
title: "Reliable External Channel Execution Requirements"
created: 2026-08-01
updated: 2026-08-01
implemented: 2026-08-01
tags: [external-channel, ingress, mailbox, session, reliability, frontend]
document_role: primary
document_type: requirements
snapshot_id: ingress-260801
---

# Reliable External Channel Execution Requirements

- Snapshot: `ingress-260801`
- Document reference: `ingress-260801/REQ`

## Problem

An accepted Slack or Discord message can remain permanently non-executing when
provider-visible Session-link or progress delivery fails, becomes unknown, or is
cancelled. The accepted provider history is already durable in the Session mailbox, but
a separate activation state prevents wake and Agent execution. Pending inputs also use
separate presentation markup, so the same input changes structure when promoted.

## Primary Actor

An authorized Slack or Discord participant who invokes an Agent and expects accepted
conversation history to reach that Agent exactly once even when an independent
provider-control operation fails.

## Primary Scenario

1. A supported provider callback is authenticated and projected into a content-free
   trigger.
2. Azents reads provider-authoritative history and durably accepts one canonical
   mailbox input for the resolved Session.
3. The accepted conversation position prevents duplicate admission.
4. Azents wakes the Session and creates the corresponding AgentRun.
5. Session-link and progress controls are attempted independently and retain their own
   delivery outcomes.

## Supporting Scenarios

- A cancelled or failed Session-link or progress attempt does not block an already
  accepted mailbox input.
- A duplicate callback recovers the existing pending wake without creating another
  Session, mailbox input, or AgentRun.
- A retained mailbox input from the removed activation flow becomes executable during
  migration without losing its conversation position.
- A newly created External Channel Session produces one content-free operational log;
  retries and Session reuse do not.
- Pending, optimistic, and promoted forms of one input use the same message
  presentation with only pending-state opacity and actions differing.

## Goals

- Guarantee that accepted External Channel input reaches ordinary Session execution.
- Keep one durable duplicate-prevention and ordering authority.
- Keep provider-control delivery durable but independent from input execution.
- Release retained inputs safely when removing obsolete activation state.
- Make Session-creation telemetry useful without exposing provider or Azents identity.
- Remove duplicate pending-message presentation.

## Non-Goals

- Retrying ambiguous provider mutations with a new uncorrelated request.
- Weakening provider authentication, ingress authority, access policy, binding
  connectedness, or provider-delivery settlement fencing.
- Making transient Gateway or Socket health an outbound REST authority.
- Retaining compatibility models or schema for the removed activation protocol.
- Changing the canonical promoted message presentation.

## Requirements

### REQ-1. Accepted input reaches execution

Once provider history is durably accepted into the canonical mailbox, provider-control
delivery outcome must not prevent Session wake, mailbox promotion, or AgentRun
creation.

**Acceptance criteria**

- Failed, unknown, not-attempted, or cancelled Session-link and progress delivery does
  not make accepted input non-promotable.
- The Session running transition, conversation-position advance, and canonical mailbox
  input commit atomically.
- Broker failure remains retryable while the mailbox item is pending.

### REQ-2. One duplicate-prevention authority

The durable conversation position must be the sole ordering and duplicate-prevention
authority for provider ingress.

**Acceptance criteria**

- Duplicate callbacks reuse the accepted mailbox identity and pending logical wake.
- A position compare-and-set conflict restarts bounded provider-history preparation.
- No activation, invocation-batch, provider-message, or wake-dispatch record duplicates
  accepted-input authority.

### REQ-3. Independent provider-control evidence

Provider-visible Session-link and progress controls must retain durable intent,
authority validation, and settlement evidence without gating accepted execution.

**Acceptance criteria**

- Controls are committed with the accepted input and attempted after commit.
- Existing delivery locking, stale-owner rejection, connection and binding
  revalidation, and one-attempt mutation fencing remain enforced.
- Delivery failure remains observable through the delivery ledger.

### REQ-4. Safe activation-state removal

The installed schema and runtime must remove obsolete Session activation state while
preserving retained accepted input.

**Acceptance criteria**

- Retained mailbox items advance their owning conversation position through the
  retained trigger and leave active Sessions runnable.
- Activation tables, enum, constraints, models, repositories, gates, and dedicated
  tests are absent after migration.
- The migration remains in one linear revision chain.

### REQ-5. Content-free creation telemetry

The first committed creation of a real External Channel root AgentSession must emit one
structured informational log.

**Acceptance criteria**

- The log contains only the provider and an allowlisted provider event type.
- Provider tenant, channel, participant, message, payload, and Session identifiers are
  absent.
- Rollback, idempotent retry, and Session reuse emit no creation log.

### REQ-6. Shared message presentation

Pending, optimistic, and promoted input must use the same message rendering component
and projection contract.

**Acceptance criteria**

- Pending presentation does not maintain a second per-message-type markup tree.
- Pending state is expressed through opacity and pending-only actions.
- External Channel, agent-mailbox, continuation, action, attachment, and ordinary user
  inputs preserve their promoted presentation behavior.

### REQ-7. End-to-end regression safety

The corrected flow must be verified through public APIs, UI behavior, and provider
fakes before release.

**Acceptance criteria**

- Deterministic Slack and Discord journeys prove ingress, mailbox acceptance, wake, and
  Agent execution.
- The access-approval replay journey proves the retained invocation executes once.
- Backend, migration, frontend, Storybook, and required pull-request CI pass on the
  latest head.

## Fixed Constraints

- Admission must remain durable before provider acknowledgement.
- Provider callback bodies are not canonical message content; provider history remains
  the content authority.
- `disconnected_at` remains the binding connectedness authority.
- Provider SDK lifecycle ownership and sanitized diagnostics remain unchanged.
- E2E verification uses public product APIs, UI, and provider fakes, never direct
  product-database writes.
- The implementation remains net line-count negative and is not merged without
  explicit requester approval.

## Open Assumptions

- Existing mailbox identity and conversation-position ordering are sufficient to
  recover one logical wake without a separate activation record.
- The provider-control worker continues recovering and attempting pending controls
  independently from Agent execution.

## Confirmation

Confirmed by the requester on 2026-08-01 through the explicit direction to treat the
Living Spec as the current behavior authority, remove activation and required-delivery
execution gates, recover the observed cancelled-progress failure, add de-identified
Session-creation telemetry, unify pending rendering, and complete verification without
additional questions.
