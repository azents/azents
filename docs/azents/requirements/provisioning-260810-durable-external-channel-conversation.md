---
title: "Durable External Channel Conversation Provisioning Requirements"
created: 2026-08-10
updated: 2026-08-10
implemented: 2026-08-10
tags: [external-channel, reliability, messaging]
document_role: primary
document_type: requirements
snapshot_id: provisioning-260810
---

# Durable External Channel Conversation Provisioning Requirements

- Snapshot: `provisioning-260810`
- Document reference: `provisioning-260810/REQ`

## Problem

An eligible External Channel message may address a provider conversation that has no
Azents Binding or AgentSession yet. Some providers must create or verify the actual
provider conversation before Azents can create that Session. Requiring provider
conversation creation, provider history, and Session input admission to finish inside
the provider callback deadline makes first-message receipt unreliable, while creating
the Session before the provider conversation exists exposes a Session whose required
external conversation is not ready.

## Primary Actor

A participant sending the first eligible message to an Azents Agent in a configured
External Channel conversation that does not yet have a Binding or AgentSession.

## Primary Scenario

A participant sends the first eligible message to a configured Discord parent channel
using per-thread conversation mode. Azents authenticates and classifies the callback,
durably retains the content-free trigger, and acknowledges the provider without waiting
for provider conversation creation or message-history reads. Azents then creates or
reuses the actual Discord thread, creates exactly one Binding and AgentSession only
after that thread is usable, and eventually admits the participant's original message
as canonical Session input without requiring a resend.

## Supporting Scenarios

- An eligible message targets a conversation whose connected Binding and AgentSession
  already exist; it continues directly into durable Session input processing without
  repeating conversation provisioning.
- Several eligible callbacks arrive for the same provider conversation before its first
  Session exists; they converge on one provider conversation, Binding, and AgentSession,
  and all retained triggers remain ordered for later Session input.
- Provider conversation creation or verification is temporarily unavailable, rate
  limited, or interrupted by process termination; the retained trigger remains
  recoverable without participant resend.
- Slack or parent-channel conversation modes use their provider's existing conversation
  identity without performing a Discord-style thread creation operation.

## Goals

- Make first-message receipt durable before provider conversation latency can exceed the
  callback deadline.
- Ensure a required provider conversation exists and is usable before exposing its new
  Binding and AgentSession.
- Preserve exactly one canonical provider conversation, Binding, and AgentSession under
  duplicate delivery and concurrent first-message callbacks.
- Preserve the original eligible trigger through eventual provider-history-backed
  canonical mailbox admission.
- Retain the existing direct durable path for conversations whose Binding and
  AgentSession already exist.

## Non-Goals

- This snapshot does not change setup, route selection, access approval, Slash Command,
  Message Command, shortcut, component, modal, or autocomplete product behavior.
- This snapshot does not change the existing Session-bound batching, canonical provider
  history, per-message mailbox, cursor, or Session wake contract after a target Session
  exists.
- This snapshot does not require a persistent Discord SDK client cache. Client reuse may
  improve latency and throughput but is not correctness authority.
- Raw provider callbacks, message bodies, credentials, signatures, interaction tokens,
  and private provider URLs do not become durable provisioning state.

## Requirements

### REQ-1. First eligible triggers survive provider conversation latency

An authenticated eligible conversation trigger that requires a new Binding and
AgentSession must acquire a durable processing identity before provider conversation
creation, verification, exact-message reads, or history reads begin.

**Acceptance criteria**

- The provider callback acknowledges after durable trigger receipt and does not wait for
  provider conversation creation, provider exact-message reads, provider history reads,
  mailbox admission, Session wake, or Agent execution.
- Provider latency, rate limiting, transient failure, process termination, or ephemeral
  execution loss after durable receipt does not erase the trigger or require the
  participant to resend it.
- Duplicate provider delivery converges on the same active trigger lifecycle while that
  lifecycle remains retained.
- Durable state contains only bounded content-free provider, conversation, routing,
  participant, and trigger identities required to continue processing.

### REQ-2. The provider conversation exists before its new Session

When a provider requires an external conversation to be created or verified for a new
Binding, that provider conversation must be usable before Azents creates the Binding
and AgentSession that represent it.

**Acceptance criteria**

- A new Discord per-thread conversation has one actual usable Discord thread before its
  Binding and AgentSession are created.
- An existing Discord thread is reused rather than duplicated.
- A Slack thread or parent-channel conversation uses its existing provider identity and
  does not perform an artificial Discord-style creation operation.
- A failed or indeterminate provider operation does not create a Binding or AgentSession
  that claims an unverified external conversation.
- Retrying after a provider operation with an uncertain result reconciles the provider
  conversation before deciding whether another creation is necessary.

### REQ-3. Concurrent first messages converge on one conversation and Session

Eligible callbacks for the same connection-scoped provider conversation must converge
on one active provisioning lifecycle and at most one connected Binding and
AgentSession.

**Acceptance criteria**

- Concurrent first-message callbacks cannot create duplicate provider conversations,
  connected Bindings, or AgentSessions.
- Every retained eligible trigger remains associated with the same resulting
  conversation and Session.
- Trigger order remains deterministic from durable receipt through later Session input
  processing.
- A callback arriving after another worker has completed provisioning observes and
  reuses the resulting connected Binding and AgentSession.

### REQ-4. Existing Sessions keep their direct durable admission path

A callback that resolves an eligible connected Binding and active AgentSession must not
repeat provider conversation provisioning.

**Acceptance criteria**

- `location=channel` traffic resolves the connection's parent-channel Binding and
  AgentSession, including messages physically received from a source thread under that
  parent conversation.
- `location=threads` traffic resolves the exact root/thread Binding and AgentSession.
- Binding selection is scoped to the current connection and cannot reuse another
  connection's Session.
- Eligible traffic with an existing target Session reaches durable Session input
  processing without provider history work in the callback.

### REQ-5. Provisioned triggers reach canonical Session input without a durability gap

After provider conversation preparation and new Session creation succeed, every
retained trigger must continue into the existing canonical Session input lifecycle
without an interval in which neither lifecycle owns it.

**Acceptance criteria**

- Process termination before, during, or after Session creation cannot leave an
  acknowledged trigger owned by neither provisioning nor Session input processing.
- The resulting Session receives each eligible retained trigger at most once as
  canonical input, subject to the existing provider-conversation cursor and duplicate
  suppression rules.
- Original durable receipt order is preserved when several retained triggers continue
  into Session input processing.
- Provider history and mailbox admission remain outside the provider callback and use
  the existing canonical content and mailbox authorities.

### REQ-6. Provisioning failure is bounded and observable

A retained first-message trigger must not remain silently stuck or disappear when
provider conversation preparation or Session creation cannot complete.

**Acceptance criteria**

- Transient provider and coordination failures remain durably retryable according to a
  bounded policy.
- A terminal or exhausted provisioning lifecycle produces a sanitized operator-visible
  failure outcome before active trigger state is removed or terminalized.
- Diagnostics identify provider, connection, safe failure category, attempt count, and
  age without exposing message bodies, participant labels, credentials, private URLs,
  or raw provider errors.
- Failure of one provider conversation does not prevent unrelated callbacks from
  independently reaching durable receipt and processing.

## Fixed Constraints

- PostgreSQL remains the durable ordering, idempotency, lifecycle, and recovery
  authority.
- Provider history remains the canonical inbound content authority.
- Existing authentication, connection fencing, route, participation, response-mode,
  access, block, Binding, Session, conversation-position, mailbox, and wake authority
  remains enforced.
- Provider conversation operations use adopted public provider SDK APIs where those
  APIs support the required operation.
- Redis, an in-memory runtime registry, and provider SDK client caches may reduce
  latency but cannot be required for correctness.
- A Discord thread required by a new per-thread conversation exists before the
  corresponding Binding and AgentSession are created.
- Durable provisioning state retains no raw provider content or credentials.

## Open Assumptions

- None.

## Confirmation

Confirmed by the requester on 2026-08-10 after the incident review established that
provider conversation provisioning precedes new Session creation while callback
acknowledgement remains independent from provider I/O.
