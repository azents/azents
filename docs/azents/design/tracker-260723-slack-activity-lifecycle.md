---
title: "Slack Activity Tracker Lifecycle Design"
created: 2026-07-23
updated: 2026-07-23
tags: [slack, external-channel, backend, engine, testenv]
document_role: primary
document_type: design
snapshot_id: tracker-260723
---

# Slack Activity Tracker Lifecycle Design

- Snapshot: `tracker-260723`
- Requirements: [`tracker-260723/REQ`](../requirements/tracker-260723-slack-activity-lifecycle.md)
- ADR: [`tracker-260723/ADR`](../adr/tracker-260723-slack-activity-lifecycle.md)

## Traceability

| Requirement | Decision | Mechanism |
| --- | --- | --- |
| `REQ-1` | `ADR-D1` | Invocation release creates Channel Work, checking presentation, and Tracker create intent before Session wake-up |
| `REQ-2` | `ADR-D1` | Work retains one provider identity; Channel Actions render full-state updates against it |
| `REQ-3` | `ADR-D2` | Finish requires a reply, attempts it first, and skips completion unless reply delivery is durable |
| `REQ-4` | `ADR-D3` | Provider deletion and `message_not_found` clear matching identity, create one replacement, and reconcile newer desired revisions |
| `REQ-5` | `ADR-D1`, `ADR-D3` | Management loads the latest progress operation scoped to the current work ID |

## Work-Cycle Start

Authorized invocation release locks the binding, commits the invocation batch and
InputBuffer reference, resolves the bound Session URL, and ensures one active work
row. New work starts with a durable `checking` payload and one `progress_create`
intent containing Slack thread coordinates, accessible fallback text, Block Kit, the
work ID, and desired revision. Credentials are not persisted. The provider attempt
runs after commit and before Session wake-up so Agent-controlled progress cannot race
a missing initial acknowledgement.

## Tracker Presentation

A shared presentation module renders `checking`, `working`, and `completed` states.
Task titles use Slack plain-text objects rather than mrkdwn. Every state includes an
`Open Azents session` URL button. The completed state omits tasks even if historical
work tasks remain available for management and audit.

The work row retains the desired payload, desired revision, and delivered provider
message identity. `continue` validates that unfinished work remains, replaces the
ordered task snapshot, advances the desired revision, and emits `progress_update`
when an identity exists. A missing identity remains visible through projection state
rather than causing an undurable provider call.

## Finish Ordering

`finish` requires a final reply. The action transaction records reply and completion
update intents in that order, marks Channel Work finished, and retains the completed
desired presentation. Delivery orchestration derives reply success from durable
ledger state as well as the current attempt result. If the reply is not delivered,
the pending completion intent becomes `not_attempted` with a stable prerequisite
error. Resuming an existing action cannot bypass this gate.

## Deletion and Reconciliation

A Slack delete revision is checked against retained Tracker identities before
connection-authored messages are excluded from canonical participant history. A
matching identity is cleared conditionally and one event-owned replacement create
intent is committed. A `progress_update` that returns confirmed
`message_not_found` creates the same replacement through the Channel Work repository.

Replacement delivery locks the owning work. When its captured desired revision is
older than the current work revision, the same transaction commits a derived
`progress_update` for the new provider identity. Delivery then attempts that update
once. If the update itself confirms deletion, the normal replacement path applies
again; ambiguous outcomes remain terminal.

## Lifecycle Cleanup

Normal finish retains the Tracker. Binding disconnect, connection disconnect,
Session archive, Agent decommission, and permanent cleanup continue to commit
`progress_delete` intents for retained provider identities. Provider cleanup occurs
after terminal local state is committed and cannot roll back lifecycle transitions.

## Test Strategy

### Primary verification matrix

| Behavior | Primary verification | Evidence |
| --- | --- | --- |
| Checking Tracker precedes wake-up | Event processor integration test | Durable create intent and provider call order |
| Todo changes update one identity | Work repository and Channel Action tests | Operation order, provider key, Block Kit payload |
| Delivered reply gates completion | Channel Action service tests | Failed/unknown/resumed reply leaves completion not attempted |
| Normal completion retains message | Work repository test | Completion uses update and preserves provider identity |
| External delete recreates Tracker | Event processor integration test | Matching identity cleared and one replacement created |
| Replacement catches newer revision | Work repository integration test | Derived update targets replacement identity and latest revision |
| Current-cycle management projection | Work repository integration test | Previous work deliveries do not affect current projection |

### E2E plan

The existing deterministic External Channel E2E remains the primary product journey:
a fake Slack provider admits an authorized invocation, observes the initial Tracker,
applies task and finish actions, and verifies one retained completed message. A
fixture-controlled delete event verifies replacement behavior without live Slack.

### Fixtures and prerequisites

Credential-free fake-provider fixtures are sufficient. Live Slack credentials are
not required for CI and must not be recorded as evidence. PostgreSQL-backed repository
tests require Docker/testcontainers locally; when Docker is unavailable they may skip
locally but must run in CI. Deterministic unit and integration failures are mandatory;
optional live-provider checks may skip only when credentials are absent.

### Evidence format and CI policy

Record exact Ruff, Pyright, Pytest, documentation validation, and deterministic E2E
commands in the PR. CI must pass backend, pre-commit, and applicable E2E jobs before
the snapshot receives an `implemented` date. Screenshots are not required because
the change is provider-message lifecycle behavior rather than an Azents Web visual
change.
