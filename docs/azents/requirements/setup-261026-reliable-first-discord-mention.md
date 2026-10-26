---
title: "Reliable First Discord Mention Requirements"
created: 2026-10-26
tags: [external-channel, discord, reliability]
document_role: primary
document_type: requirements
snapshot_id: setup-261026
---

# Reliable First Discord Mention Requirements

- Snapshot: `setup-261026`
- Document reference: `setup-261026/REQ`

## Problem

An eligible Discord mention in an unconfigured channel can be received successfully but fail before the setup prompt appears. A process-local background task removes the short callback deadline but does not preserve unfinished work across process termination or Gateway replacement.

## Primary System Outcome

An eligible first Discord mention remains recoverable until setup preparation produces its existing setup/selection/access outcome or reaches a bounded, explicitly observable terminal outcome, independently of the Gateway connection lifetime.

## Supporting Scenarios or Effects

- Slow provider reads do not prevent subsequent Gateway callbacks or lifecycle handling.
- Duplicate delivery and repeated mentions converge on the existing channel-scoped setup lifecycle.
- User selection continues through the existing settings and conversation provisioning flow.

## Goals

- Preserve an eligible setup trigger before provider history or setup-control work.
- Recover interrupted work and retry explicitly retryable failures within finite limits.
- Keep existing user-visible setup and permission behavior.

## Non-Goals

- Changing setup controls, response modes, Agent selection, or access policy.
- Creating a Binding, AgentSession, or AgentRun before the existing setup/access requirements are satisfied.
- Replacing the configured-conversation ingress queue or common Job Runtime.
- Generalizing every Slack callback or every Discord interaction in this change.
- Claiming exactly-once provider delivery after an ambiguous external mutation.
- Implementing the broader observability work tracked separately in #2464.

## Requirements

### REQ-1. Preserve setup work before slow provider processing

An eligible unconfigured top-level Discord mention is recoverable before provider exact-message/history reads or setup-control delivery begin.

**Acceptance criteria**

- Delaying provider reads beyond 2.5 seconds does not erase the received setup trigger or block the Gateway callback.
- A process exit after receipt but before local work starts does not require the participant to repeat the mention.
- Durable state contains only bounded identities and control state, never message bodies, raw payloads, callback secrets, or credentials.

### REQ-2. Recover independently from transport replacement

An ordinary Gateway reconnect does not invalidate already admitted setup preparation. Actual connection/configuration changes, disconnection, source replacement, and permission or Agent lifecycle changes remain authoritative.

**Acceptance criteria**

- Another eligible producer can resume unfinished preparation after execution ownership expires.
- Concurrent producers cannot both commit a stale result or overwrite a newer source/selection.
- Repeated provider delivery does not create independent copies of the same setup work.

### REQ-3. Preserve existing setup behavior and authority

Setup preparation produces the existing Agent-selection, location-selection, access, or ignored outcome without preempting participant decisions.

**Acceptance criteria**

- Unselected setup creates no Binding, AgentSession, mailbox input, or AgentRun.
- Repeated mentions follow the existing latest-eligible-source rule.
- A selected or invalidated setup source cannot be overwritten by an older preparation attempt.
- Existing configured channels continue using their current durable ingress lifecycle.

### REQ-4. Bound failures without blind provider replay

Temporary failures receive bounded retry/recovery. Terminal or ambiguous outcomes are handled without silently losing failure evidence or blindly repeating an uncertain provider mutation.

**Acceptance criteria**

- Permanent source unavailability, stale authority, retry exhaustion and age exhaustion reach explicit terminal handling.
- No failed setup work forces closure of a healthy Gateway client.
- Provider-control ambiguity is not represented as a confirmed successful delivery or retried as though no effect occurred.

## Fixed Constraints

- PostgreSQL owns durable lifecycle authority; Redis and process-local execution are not correctness authorities.
- Preserve existing provider SDK boundaries, permission checks, setup claims and Job Runtime integration.
- Keep the quick process-local fix independently releasable; this follow-up has no automatic merge approval.

## Open Assumptions

- Scope is the affected Discord first-setup path; widening Slack behavior is not required for this repair.
- Broader timing and failure observability remains a separate improvement.

## Confirmation

The requester confirmed this requirement snapshot and the existing setup-claim extension direction on 2026-10-26, after the separately releasable process-local quick fix. The confirmation preserves the existing setup workflow and excludes automatic merge of this follow-up.
