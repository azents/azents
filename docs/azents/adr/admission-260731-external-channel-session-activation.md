---
title: "External Channel Session Activation"
created: 2026-07-31
updated: 2026-07-31
tags: [external-channel, session, admission, delivery, recovery, architecture]
document_role: primary
document_type: adr
snapshot_id: admission-260731
---

# External Channel Session Activation

- Snapshot: `admission-260731`
- Document reference: `admission-260731/ADR`
- Requirements: [`admission-260731/REQ`](../requirements/admission-260731-external-channel-session-activation.md)

## Context

The current protocol commits a Session, binding, work projection, and provider delivery intents, performs provider mutations, and only then attempts to create the canonical mailbox input and mark the Session running. It has no durable record that owns the triggering invocation across those boundaries. A provider-visible Session link may therefore be delivered while later mailbox admission fails, and retries must reconstruct progress from unrelated binding, work, delivery, mailbox, and conversation-position rows.

The requester fixed the required order as: bind a real Session and retain its canonical non-executing mailbox input, deliver the Session link, deliver the initial tracker, then activate, run, and wake the Session.

## Decision Backlog

- [x] Durable authority for one in-progress Session activation.
- [x] Exact ordering of binding, mailbox retention, provider initialization, activation, and wake.
- [x] Required-delivery identity and ordering.
- [x] Conversation ordering while an activation is incomplete.
- [x] Failure and recovery classification.
- [x] Activation and broker-wake transaction boundary.
- [x] Session visibility and URL contract.
- [x] Existing-data and rollout behavior.

## Accepted Decisions

### admission-260731/ADR-D1 — A dedicated activation record owns the invocation

Create one durable External Channel Session activation for each canonical trigger identity. It owns the conversation position and trigger boundary, binding, Session, activation state, optional mailbox identity, and ordered links to required delivery attempts.

The activation record is the sole admission-progress authority. Binding connectedness remains owned only by `disconnected_at`; AgentSession runtime state, mailbox presence, delivery payload JSON, Redis, and in-memory locks do not substitute for activation state.

Affected requirements: `admission-260731/REQ-1`, `admission-260731/REQ-4`, `admission-260731/REQ-5`, `admission-260731/REQ-6`.

Rejected alternatives:

- Infer progress from binding, work, delivery, mailbox, and Session rows. Their independent lifecycles cannot prove which trigger they jointly represent.
- Reintroduce a binding status. Connectedness and execution admission are separate concerns.

### admission-260731/ADR-D2 — The protocol follows the requester-defined order

The shared protocol is:

1. create or reuse the durable activation, binding, and real root Session;
2. create or reuse the canonical non-executing mailbox input;
3. deliver the Session link;
4. deliver every initial tracker part in stable order;
5. atomically activate the record, mark the Session running, and advance conversation positions; and
6. dispatch the broker wake after commit.

Every step starts only after the preceding durable state proves success. Provider I/O never occurs inside a database transaction.

Affected requirements: `admission-260731/REQ-1` through `admission-260731/REQ-7`.

The mailbox item is a durable retained input but remains outside promotion and wake eligibility until the activation reaches `activated`.

Rejected alternatives:

- Create the mailbox input only after provider initialization. A crash or authority loss after visible provider mutation can still lose the canonical trigger input.
- Keep the current anonymous `stage`/`finalize` handoff. It cannot recover one invocation as a durable unit.

### admission-260731/ADR-D3 — Required provider deliveries are explicit ordered children

Each activation links to its required provider delivery attempts with a stable ordinal. Ordinal zero is the Session link; later ordinals are initial tracker parts. Existing one-attempt delivery rows remain the provider mutation fence. Activation uses only its linked attempts and requires every linked attempt to be durably `delivered`.

Failed, unknown, or not-attempted provider outcomes are never replaced or blindly replayed.

Affected requirements: `admission-260731/REQ-2`, `admission-260731/REQ-3`, `admission-260731/REQ-5`.

### admission-260731/ADR-D4 — Incomplete activation is the conversation-order barrier

A conversation position may have at most one incomplete activation. A later trigger must recover or observe that activation before it can create another executable admission. Conversation positions advance only in the mailbox-admission and activation transaction.

This ordering is PostgreSQL-owned. Redis or in-memory locks may reduce contention but are not correctness authorities.

Affected requirements: `admission-260731/REQ-5`, `admission-260731/REQ-6`, `admission-260731/REQ-7`.

### admission-260731/ADR-D5 — Activation has explicit non-running terminal outcomes

Activation states are `initializing`, `activated`, and `blocked`.

- `initializing` covers the committed binding, retained mailbox input, and provider initialization that may still complete.
- `activated` proves mailbox promotion eligibility, running transition, and position advancement committed together.
- `blocked` records a known failed, unknown, revoked, inconsistent, or otherwise non-recoverable initialization outcome while retaining the mailbox input.

Neither `initializing` nor `blocked` may run or wake the Session. A delivered link remains valid because the bound Session is retained and queryable.

Affected requirements: `admission-260731/REQ-1`, `admission-260731/REQ-2`, `admission-260731/REQ-3`, `admission-260731/REQ-5`.

### admission-260731/ADR-D6 — Activation commits before an idempotent broker wake

Activation `initializing -> activated`, Session running transition, and conversation-position advancement occur in one short transaction for the already retained mailbox item. Broker wake occurs after commit and uses that canonical mailbox item as its recovery identity.

A crash before the activation commit leaves a retained but non-promotable mailbox input. A crash after commit leaves the activated mailbox item available for wake recovery. Activation never rolls backward.

Affected requirements: `admission-260731/REQ-4`, `admission-260731/REQ-5`.

### admission-260731/ADR-D7 — Existing Session APIs expose retained Sessions and links use `/w`

The root Session is committed before provider delivery and remains an active, idle Session until activation. Existing Session get/list authorization and projections remain the public authority; no synthetic Session or compatibility route is added.

The only generated link shape is `/w/{workspace}/agents/{agent}/sessions/{session}`.

Affected requirements: `admission-260731/REQ-1`, `admission-260731/REQ-2`.

### admission-260731/ADR-D8 — Rollout is additive and reuses legacy identities conservatively

The new activation tables are additive. Existing connected bindings, Sessions, work, delivery attempts, mailbox items, and positions remain intact.

A retried legacy staged invocation may create an activation and canonical mailbox item that reuse the existing binding, Session, work, and one-attempt deliveries. Existing mailbox and advanced-position evidence remains handled by the duplicate wake-recovery path. Delivered provider controls alone never imply that execution occurred.

Affected requirements: `admission-260731/REQ-2`, `admission-260731/REQ-5`, `admission-260731/REQ-7`.

## Consequences

- Recovery can query one durable record instead of reconstructing an invocation from unrelated rows.
- Provider links always target committed Sessions, including blocked non-executing Sessions.
- Known terminal delivery ambiguity can leave a conversation intentionally blocked until lifecycle intervention; it cannot silently execute or replay a provider mutation.
- The current `prepare -> stage -> deliver -> finalize` protocol types and tests must be replaced as one unit.
