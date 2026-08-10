---
title: "Durable External Channel Conversation Provisioning Decisions"
created: 2026-08-10
tags: [architecture, external-channel, reliability, messaging]
document_role: primary
document_type: adr
snapshot_id: provisioning-260810
---

# provisioning-260810/ADR: Durable External Channel Conversation Provisioning

- Snapshot: `provisioning-260810`
- Document reference: `provisioning-260810/ADR`
- Requirements:
  [`provisioning-260810/REQ`](../requirements/provisioning-260810-durable-external-channel-conversation.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

The implemented `channel-260810` lifecycle admits only triggers that already have an
immutable target Session. A new or incorrectly resolved source Resource therefore
falls back to synchronous provider history under the provider callback deadline.

The new Requirements add a durable boundary for eligible triggers whose provider
conversation, Binding, and AgentSession do not exist yet. For Discord per-thread
conversations, the actual provider thread must be usable before Azents creates the
Binding and AgentSession. Existing connected Sessions retain the current direct
Session-bound ingress lifecycle.

## Fixed and Derived Outcomes

- A configured trigger admitted by this snapshot performs no provider conversation
  mutation, exact-message read, history read, mailbox admission, Session wake, or Agent
  execution before provider acknowledgement. Existing unconfigured setup and pending
  access outcomes retain their current product lifecycle.
- PostgreSQL owns durable pre-Session receipt, idempotency, ordering, retry state, and
  recovery in one ingress lifecycle that later records its resulting Session.
- Existing eligible Binding and Session resolution starts the same ingress lifecycle
  with its Session identity already resolved.
- A Discord thread required by a new per-thread conversation exists before its
  Binding and AgentSession.
- Provider history and canonical mailbox admission remain in the existing
  Session-bound drain after a Session exists.
- Durable state remains content-free and Redis, Local Job Runtime registration, and
  provider SDK client caches remain wake or performance mechanisms rather than
  correctness authority.
- Existing setup, selection, access, response-mode, cursor, mailbox, batching, and
  Session-wake product behavior remains unchanged.

## Material Decision Map

| ID | State | Decision |
| --- | --- | --- |
| `provisioning-260810/ADR-D1` | Superseded by D3 | Use a distinct durable conversation-provisioning lifecycle before Session-bound ingress |
| `provisioning-260810/ADR-D2` | Accepted | Remove exhausted provisioning work after sanitized failure logging |
| `provisioning-260810/ADR-D3` | Accepted | Generalize the ingress queue to create and record its target Session |

Provider conversations created before an interrupted DB Session commit are governed by
`provisioning-260810/REQ-2`: retry reconciles and reuses the provider conversation
rather than treating automatic deletion as an open decision.

## Agent-Owned Implementation Categories

The Design may choose equivalent local details without additional requester decisions:

- table, repository, model, handler, state, metric, and diagnostic field names;
- provider policy interface and module boundaries;
- deterministic provider-conversation and trigger idempotency-key encoding;
- lock ordering, query composition, and transaction helper structure;
- bounded claim sizes and local Job Runtime submission keys that preserve approved
  ordering and recovery;
- fixture composition, test helper names, and migration SQL layout; and
- bounded SDK client-cache implementation details if that optimization is included
  later under its already agreed eviction and fencing constraints.

These choices cannot introduce another durable authority, acknowledge before durable
receipt, create a Session before its required provider conversation, or silently
discard a retained trigger.

## Accepted Decisions

### provisioning-260810/ADR-D1 — Provision new conversations before Session-bound ingress

Eligible callbacks first resolve an existing connected Binding and active AgentSession.
When one exists, the trigger enters the existing Session-bound ingress lifecycle
directly.

When no target Session exists, the callback durably inserts or reuses a
connection-scoped provider-conversation provisioning lifecycle and acknowledges after
that transaction commits. The provisioning lifecycle retains every eligible
content-free trigger for that provider conversation.

A provider-specific provisioning policy then creates, verifies, or reuses the actual
provider conversation. Discord per-thread provisioning reconciles or creates the
actual Discord thread before Session creation. Slack threads and parent-channel modes
use their already existing provider conversation identity without an artificial
thread-creation mutation.

After provider conversation authority is established, one transaction creates or
reuses the Resource, Binding, AgentSession, and required initial Session state; inserts
or reuses every retained trigger in the existing Session-bound ingress lifecycle in
durable receipt order; and completes the provisioning lifecycle. Process termination
cannot leave an acknowledged trigger owned by neither lifecycle.

Concurrent callbacks for the same connection-scoped provider conversation converge on
one active provisioning owner and at most one connected Binding and AgentSession.

Affected requirements: `provisioning-260810/REQ-1`, `provisioning-260810/REQ-2`,
`provisioning-260810/REQ-3`, `provisioning-260810/REQ-4`, and `provisioning-260810/REQ-5`.

Rejected alternatives:

- Create a Discord Binding and AgentSession before the actual provider thread exists.
  This exposes a Session whose required external conversation is not usable.
- Perform provider thread creation inside the provider callback. This restores
  provider latency as an acknowledgement and message-loss boundary.
- Extend the existing Session-bound ingress item with an absent or provisional
  Session identity. This weakens its immutable Session authority and mixes
  pre-Session provisioning with canonical Session input processing.
- Fall back to synchronous ingestion when no exact source Binding exists. This is the
  incident-producing path the new snapshot removes.

### provisioning-260810/ADR-D2 — Bound retry and remove exhausted provisioning work

Provisioning uses a bounded automatic attempt and age budget. A retryable failure keeps
the provider-conversation owner and every retained trigger active until the next due
attempt. Attempt exhaustion, age exhaustion, an excessive provider retry delay, stale
authority, or a provider-classified terminal failure emits one sanitized structured
failure log and removes the active provisioning owner and its retained triggers.

No completed, failed, dead-letter, or operator-retry provisioning row remains.
Subsequent provider redelivery or a later eligible callback may create a new
provisioning lifecycle with a new retry budget when no connected Binding and
AgentSession exist.

Affected requirements: `provisioning-260810/REQ-1`,
`provisioning-260810/REQ-3`, and `provisioning-260810/REQ-6`.

Rejected alternatives:

- Retain exhausted provisioning work as a durable failed outcome requiring manual
  retry or discard. This introduces a second terminal queue and management lifecycle
  inconsistent with active-only Session ingress.
- Retry automatically without a bounded terminal point. This can create Sessions long
  after the initiating callback and permits permanently unhealthy conversations to
  consume unbounded active retry capacity.

### provisioning-260810/ADR-D3 — Let one conversation-bound ingress queue create its Session

This decision supersedes `provisioning-260810/ADR-D1`.

The ingress lifecycle is generalized from an immutable Session-bound owner into a
connection-scoped effective-conversation owner whose Session identity may be absent
until provisioning succeeds. The callback computes the effective target conversation,
inserts or reuses that queue owner, and appends one independently deduplicated trigger.
Every later callback for the same future Binding and Session appends another trigger to
the same active owner without waiting for a time or count accumulation window.

The first eligible trigger starts processing immediately. The queue worker performs
the provider-specific conversation preparation once for the owner, creates or reuses
the Resource, Binding, and AgentSession after provider conversation authority exists,
and records the resulting Session on that same owner. The retained trigger rows do not
move to another queue. The worker then processes them through the existing
provider-history, cursor, mailbox, batching, and Session-wake lifecycle in durable
receipt order.

Callbacks arriving while provider conversation or Session creation is in progress
continue appending to the same owner. After Session creation, later items use the same
first-one/later-ten batching contract. When the owner becomes empty, it is deleted; a
later callback recreates an owner already bound to the existing Session.

The queue execution identity is stable for the owner lifecycle and does not depend on
an AgentSession existing at admission time. PostgreSQL owner and item state remains the
durable authority; Local Job Runtime submission remains only a recoverable wake.

Affected requirements: `provisioning-260810/REQ-1`,
`provisioning-260810/REQ-2`, `provisioning-260810/REQ-3`,
`provisioning-260810/REQ-4`, and `provisioning-260810/REQ-5`.

Rejected alternatives:

- Retain D1's separate provisioning queue and transfer its triggers into a second
  Session-bound queue. Deterministic effective-conversation ownership already groups
  every trigger that will share one Session, so a second durable queue adds handoff,
  cutover, ordering, and recovery state without adding authority.
- Keep Session identity mandatory and create a placeholder AgentSession before provider
  conversation preparation. This violates the required Discord thread-before-Session
  order.
