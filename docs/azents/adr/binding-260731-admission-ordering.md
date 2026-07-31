---
title: "External Channel Binding and Admission Ordering"
created: 2026-07-31
tags: [external-channel, binding, ingress, delivery, architecture]
document_role: primary
document_type: adr
snapshot_id: binding-260731
---

# External Channel Binding and Admission Ordering

- Snapshot: `binding-260731`
- Requirements:
  [binding-260731/REQ](../requirements/binding-260731-admission-ordering.md)
- Document reference: `binding-260731/ADR`

## Context

External Channel bindings currently duplicate one terminal fact across an
`active`/`disconnected` status and `disconnected_at`. Provider delivery authority also
uses transient connection health even though Slack and Discord outbound operations use
provider REST APIs rather than the persistent ingress transport.

The synchronous ingress path currently commits the binding, mailbox input, conversation
position, Session running transition, wake identity, and initial provider-control
intents together. Provider controls run only after that commit. This allows Agent
execution to start before the provider-visible Session navigation and initial progress
projection exist.

The confirmed Requirements fix the product boundaries. The remaining decisions define
the durable authority and transaction boundaries used to implement them.

## Decision Backlog

- [x] Represent binding connectedness through one terminal timestamp.
- [x] Split synchronous admission into durable stage and mailbox finalize transactions.
- [x] Treat required initial provider deliveries as durable one-attempt gates.
- [x] Separate outbound REST authority from persistent-ingress health.
- [x] Derive new Discord conversation titles from the current Agent identity.

## Decisions

### binding-260731/ADR-D1. Binding connectedness has one durable authority

Binding connectedness is represented by `disconnected_at IS NULL`. Explicit
disconnect sets `disconnected_at` and a bounded `disconnect_reason`. The binding status
enum and column are removed from persistence, domain projections, public schemas,
generated clients, and UI state.

`disconnected_at` is a terminal boundary. No code clears it or reuses a disconnected
binding as the current relationship. Partial unique indexes enforce at most one
connected binding for a resource.

This satisfies binding-260731/REQ-1 without maintaining two fields that can disagree.

Rejected alternatives:

- Retain `active`/`disconnected` as a derived public status. This preserves the product
  concept the Requirements explicitly remove and leaves two representations.
- Add more transient binding states for initialization. This would couple the durable
  relationship to execution or provider-delivery progress.

### binding-260731/ADR-D2. Ingestion uses stage, required delivery, and finalize

Synchronous conversation ingestion has three ordered boundaries:

1. a short database transaction creates or reuses the binding, root Session, initial
   Channel Work, and deterministic provider-delivery intents;
2. the orchestrator settles every required initial delivery outside a database
   transaction; and
3. a second short database transaction revalidates authority and delivery results,
   enqueues the canonical mailbox item, marks the Session runnable, advances the
   conversation position, and commits wake-recovery identity.

Provider I/O never occurs while a database transaction is open. The conversation lock
and current ingress-authority fence cover the complete operation, including the
provider-delivery interval.

This satisfies binding-260731/REQ-2 and binding-260731/REQ-3.

Rejected alternatives:

- Perform provider I/O in the acceptance transaction. This holds locks across network
  calls and cannot atomically roll back an external side effect.
- Admit the mailbox first and delay provider initialization. This permits Agent
  execution before the required provider-visible state exists.

### binding-260731/ADR-D3. Required initialization reuses the delivery ledger

Session navigation and initial progress use deterministic delivery-attempt identities
and the existing delivery ledger. A retry observes `delivered` as complete, attempts
`pending` through the normal one-attempt provider boundary, waits for an in-flight
`attempting` result only within the operation deadline, and fails closed for
`failed`, `unknown`, missing, or incomplete results.

Mailbox finalization locks and verifies every required attempt belongs to the staged
binding and is `delivered`. It never infers success from an expired Redis lock, process
memory, a provider acknowledgement timeout, or a missing ledger row.

This satisfies binding-260731/REQ-3 and binding-260731/REQ-4.

Rejected alternatives:

- Issue a new provider request after an ambiguous outcome. This can duplicate an
  externally visible mutation.
- Use Redis or an in-process task as completion authority. Neither is durable or
  required for correctness.

### binding-260731/ADR-D4. Outbound authority excludes ingress health

Outbound provider delivery validates the non-disconnected binding, active Agent and
Session, current route/resource ownership, configured credentials, directional
capability, and operation-specific action authority. It does not require connection
health to be `active` and does not inspect Gateway/Socket lease, heartbeat, gap, or
reconnect state.

Connection terminal disconnect still revokes credentials and terminalizes owned
bindings/resources, so outbound delivery fails through those durable authority
boundaries. Provider REST outcomes remain the delivery result authority.

This satisfies binding-260731/REQ-5.

Rejected alternative:

- Keep connection health as an outbound precondition. Persistent-ingress recovery
  would continue to block an otherwise valid REST operation.

### binding-260731/ADR-D5. Discord creation title is an Agent snapshot

When Azents creates a Discord conversation channel or thread, the provider adapter
receives a bounded title derived from the current routed Agent name. The title is used
only for creation. Existing provider titles are preserved, and later Agent renames do
not trigger provider renames.

This satisfies binding-260731/REQ-6.

Rejected alternatives:

- Use a fixed product title. It provides less conversation context.
- Continuously synchronize the provider title. It would add an unrelated lifecycle,
  authorization, and retry surface.

## Consequences

- The public `ManagedBinding` contract loses its `status` field. Consumers derive
  terminal display from `disconnected_at`.
- A schema migration removes the binding status column and PostgreSQL enum after
  replacing status-based indexes with `disconnected_at` predicates.
- Initial provider delivery latency is now part of synchronous transport admission.
  Optional provider-history enrichment must not consume the time reserved for required
  delivery and durable finalization.
- A staged binding may exist before its first mailbox item. Retrying the same provider
  event must complete or observe the same durable initialization rather than create a
  second binding or Session.
- Gateway health remains observable and authoritative for inbound ownership only.
