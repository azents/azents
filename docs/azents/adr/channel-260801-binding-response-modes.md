---
title: "External Channel Binding Response Modes"
created: 2026-08-01
tags: [architecture, external-channel, agent, session]
document_role: primary
document_type: adr
snapshot_id: channel-260801
---

# channel-260801/ADR: External Channel Binding Response Modes

## Context

The confirmed
[channel-260801/REQ](../requirements/channel-260801-binding-response-modes.md)
requires each connected External Channel binding to have one concrete response mode:
`mention_only` or `all_messages`. Each Agent also has an `all_messages` default that is
copied when a binding is created. Agent-default changes are not retroactive, while a
binding-mode change affects future message handling without cancelling or reclassifying
accepted work.

The current provider adapters already distinguish an explicit invocation from an
ordinary message. This distinction currently controls whether an unbound provider
conversation may create a resource. Once a resource and connected binding exist,
ordinary eligible human messages continue the same Session without mentioning the
Agent. Slack already subscribes to ordinary message events, Discord already receives
Guild messages, and both providers enter one shared synchronous ingestion service.

The shared ingestion service resolves the provider resource and locks its connected
binding before provider-history retrieval. It repeats binding resolution under lock in
the final admission transaction, where it validates authorization, creates or reuses
the Session and binding, enqueues canonical mailbox input, advances the durable
conversation position, and marks the Session running. Binding creation also occurs
through the administrator Allow path.

The Requirements fix the supported modes, `all_messages` compatibility defaults,
creation-time copy behavior, Agent Settings and Session Channels surfaces,
non-retroactive updates, contextual retention of non-trigger messages, and preservation
of current authorization, cursor, mailbox, wake, and delivery contracts. Those product
decisions are not reopened here.

## Decision Backlog

1. **Accepted: binding policy evaluation boundary** — the shared synchronous ingestion
   service owns response-mode evaluation after binding resolution.
2. **Accepted: transactional effective-time boundary** — reuse the existing ingestion
   transactions and ordinary PostgreSQL row update locking without adding a
   policy-specific lock or revision protocol.
3. **Accepted: Agent-default persistence and management contract** — store the required
   scalar on the Agent row and expose it through Agent-scoped External Channel
   management rather than a separate settings root or generic Agent patch contract.

Exact enum and endpoint names, localized UI wording, and ordinary scalar
last-write-wins mutation behavior remain reversible Design details rather than
requester decisions.

## Decisions

### channel-260801/ADR-D1 — Shared ingestion owns binding response-mode evaluation

The shared synchronous ingestion service evaluates the connected binding's concrete
response mode after resolving the provider resource and binding. Provider-specific
Slack and Discord adapters continue to authenticate callbacks, normalize provider
identity, and classify whether a message is an explicit invocation. They do not query,
cache, or interpret Agent-default or binding response policy.

For an unbound conversation, the existing explicit-invocation signal continues to
control whether a resource and binding may be created. For an already connected
binding, shared ingestion combines that signal with the binding's concrete mode:
`all_messages` permits the current ordinary eligible continuation path, while
`mention_only` ignores an ordinary non-invocation without creating canonical input or
advancing the conversation position. Existing explicit invocation mechanisms continue
through the normal path.

This decision applies to `channel-260801/REQ-2`, `REQ-4`, `REQ-5`, and `REQ-8`.

Provider-specific policy evaluation is rejected because it would duplicate binding,
connectedness, and configuration authority across Slack and Discord. It would also
require each adapter to resolve durable provider-resource aliases and policy-update
races that the shared ingestion service already owns.

### channel-260801/ADR-D2 — Existing transaction boundaries apply current committed policy

Response-mode handling reuses the short preparation and final admission transactions
already required by synchronous ingestion. Preparation may avoid provider-history work
when the currently resolved connected binding is `mention_only` and the message is not
an explicit invocation. Final admission resolves the binding again through the existing
locked path and applies the mode visible in that transaction before canonical input or
conversation-position advancement.

A binding-mode mutation uses an ordinary update of the same binding row. PostgreSQL's
normal update and existing ingestion row locking provide the database serialization
that already exists; this feature adds no policy-specific lock, revision counter, CAS
contract, or retry protocol. No lock is held across provider I/O.

Binding creation reads and copies the Agent default in the same transaction that creates
the concrete binding. An Agent-default save completed before that read is visible to the
new binding. An exact concurrent default update and binding creation race receives no
additional ordering guarantee beyond normal transaction visibility.

This decision applies to `channel-260801/REQ-2`, `REQ-4`, and `REQ-7`.

A new long-lived or policy-specific lock is rejected because the current ingestion and
update transactions already provide the required lifecycle safety. Request-level policy
versions and forced retries are rejected because the scalar setting does not justify
additional state, provider-history reads, or acknowledgement delay.

### channel-260801/ADR-D3 — Agent owns a required scalar managed by External Channel APIs

The Agent row stores one required default response-mode enum. Every External Channel
binding row separately stores one required concrete response-mode enum. Both columns
use `all_messages` for new rows and migration of existing rows. Binding creation copies
the Agent column into the binding column in both normal synchronous ingestion and
administrator Allow creation paths.

Agent Settings reads and updates the Agent default through the Agent-scoped External
Channel management contract. The default remains available when the Agent has no
configured connection. The generic Agent response, create request, and patch contract
do not gain an External Channel-specific field. Session Channels projects the concrete
binding mode and updates only a connected binding through its existing AgentAdmin and
Session ownership boundary.

This decision applies to `channel-260801/REQ-1`, `REQ-2`, `REQ-3`, and `REQ-6`.

A separate one-to-one External Channel Agent settings table is rejected because a
single required scalar would gain missing-row semantics, another lifecycle root, and
Agent-creation coupling without an independent lifecycle. Adding the setting to the
generic Agent public contract is rejected because it would broaden unrelated Agent
read, create, patch, generated-client, and UI fixture surfaces while bypassing the
existing External Channel settings boundary.

## Existing Decisions Preserved

- `channel-260729/ADR-D1` remains authoritative: authenticated Slack HTTP, Slack Socket
  Mode, and Discord Gateway transports directly invoke one shared synchronous
  ingestion service.
- `channel-260729/ADR-D2` remains authoritative: PostgreSQL conversation positions are
  the durable ordering authority behind ephemeral coordination locks.
- `channel-260729/ADR-D3` remains authoritative: approval replay reuses the same
  synchronous ingestion service and immutable provider-history boundary.

## Risks to Resolve

- Evaluating policy in more than one layer would create provider-specific behavior and
  race-prone duplicate authorities.
- Using a stale request-start policy after a saved change could violate the required
  future-message boundary.
- A nullable, inherited, or missing Agent or binding mode would create an unapproved
  compatibility fallback.
- Binding creation through normal ingestion and administrator Allow must copy the same
  authoritative Agent default.
