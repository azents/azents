---
title: "Reliable External Channel Execution"
created: 2026-08-01
updated: 2026-08-01
tags: [external-channel, ingress, mailbox, session, architecture]
document_role: primary
document_type: adr
snapshot_id: ingress-260801
---

# Reliable External Channel Execution

- Snapshot: `ingress-260801`
- Document reference: `ingress-260801/ADR`
- Requirements:
  [`ingress-260801/REQ`](../requirements/ingress-260801-reliable-external-channel-execution.md)

## Context

The implemented activation protocol made successful provider-control delivery a
prerequisite for mailbox promotion, Session wake, and Agent execution. A real cancelled
progress operation demonstrated that this coupling could strand an already durable
provider invocation indefinitely. Conversation positions and mailbox identity already
provide the required durable ordering, idempotency, and wake-recovery evidence.

## Decision Backlog

- [x] Accepted-input and duplicate-prevention authority.
- [x] Relationship between provider-control delivery and Agent execution.
- [x] Existing activation-state migration behavior.
- [x] Pending and promoted message presentation ownership.

## Accepted Decisions

### ingress-260801/ADR-D1 — Conversation position and mailbox own accepted ingress

The PostgreSQL conversation position is the sole provider-ingress ordering and
duplicate-prevention authority. The canonical mailbox item owns accepted input and
pending wake recovery.

Session activation, provider-message copies, invocation batches, and separate wake
records do not duplicate that authority.

Affected requirements: `ingress-260801/REQ-1`, `ingress-260801/REQ-2`,
`ingress-260801/REQ-4`.

Rejected alternatives:

- Repair the activation state machine. It retains a second authority whose terminal
  states can contradict durable mailbox acceptance.
- Use Redis or an in-memory lock as the duplicate fence. Those mechanisms cannot own
  durable correctness or recovery.

### ingress-260801/ADR-D2 — Provider controls are independent durable work

Session-link and progress intents commit alongside accepted input, but their delivered,
failed, unknown, not-attempted, or cancelled outcomes never gate mailbox promotion,
Session wake, or AgentRun creation.

The existing provider-delivery ledger remains authoritative for mutation identity,
locking, revalidation, and settlement.

Affected requirements: `ingress-260801/REQ-1`, `ingress-260801/REQ-3`.

Rejected alternatives:

- Make successful provider mutation part of accepted-input semantics. External side
  effects cannot be atomic with the database transaction and must not suppress durable
  user input.
- Remove durable controls entirely. Provider-visible navigation and progress still
  require recoverable intent and outcome evidence.

### ingress-260801/ADR-D3 — Activation removal releases retained mailbox input

The schema migration advances each retained activation's conversation position through
its trigger, marks its active Session runnable, and then removes activation tables,
constraints, and enum state. Runtime code has no compatibility reader or fallback for
the removed schema.

Affected requirements: `ingress-260801/REQ-4`.

Rejected alternatives:

- Drop activation rows without releasing retained inputs. This would leave accepted
  work stranded or vulnerable to duplicate re-admission.
- Preserve read-only activation models. They would keep obsolete authority in the
  runtime and complicate future correctness reasoning.

### ingress-260801/ADR-D4 — MessageBubble owns pending and promoted rendering

Pending mailbox, buffered, and optimistic inputs are projected into the canonical chat
message shape and rendered by `MessageBubble`. Pending state contributes only opacity
and actions.

Affected requirements: `ingress-260801/REQ-6`.

Rejected alternatives:

- Keep a separate pending renderer synchronized with promoted presentation. The
  duplicated markup has already drifted by message type.
- Promote pending entries into canonical history early. Pending presentation must not
  change durable event ownership.

## Consequences

- Provider-visible controls may arrive after Agent execution starts or may fail while
  execution continues.
- Accepted ingress has fewer durable states and recovery branches.
- Historical activation Requirements, ADR, and Design remain immutable records; the
  Living Specs describe the current system.
- UI changes to canonical message rendering automatically apply to pending projections.

## Risks and Mitigations

- **Risk:** A pending provider control is not attempted promptly.
  **Mitigation:** The durable provider-control worker continues bounded recovery and
  delivery independently from ingress.
- **Risk:** Migration releases a retained input whose provider control failed.
  **Mitigation:** This is intentional accepted-input recovery; the mailbox row and
  trigger position must both exist before release.
- **Risk:** Creation telemetry leaks identity.
  **Mitigation:** Event kinds are allowlisted and tests assert the absence of provider
  and Session identifiers.
