---
title: "Discord Todo Work Activity Tracker Visibility Design"
created: 2026-08-29
updated: 2026-08-29
implemented: 2026-08-29
tags: [discord, external-channel, activity-tracker, backend, testenv]
document_role: primary
document_type: design
snapshot_id: tracker-260829
---

# tracker-260829/DESIGN: Discord Todo Work Activity Tracker Visibility

- Snapshot: `tracker-260829`
- Document reference: `tracker-260829/DESIGN`
- Requirements:
  [`tracker-260829/REQ`](../requirements/tracker-260829-todo-work-visibility.md)
- Decisions:
  [`tracker-260829/ADR`](../adr/tracker-260829-todo-work-visibility.md)

## Current Behavior and Gap

Discord ordinary all-messages admission creates a Channel Work cycle with
`tracker_visibility=hidden`. Explicit invocation can later promote that state through
`ensure_active_work`, but `channel_action continue` currently updates title, tasks, and
desired progress while retaining hidden visibility. Effect planning then suppresses
the progress create/update.

The result is canonical unfinished Todo state without a visible Activity Tracker,
contrary to `tracker-260829/REQ-1`.

## Requirement Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `tracker-260829/REQ-1` | M1, M2 |
| `tracker-260829/REQ-2` | M1, M2, M3 |
| `tracker-260829/REQ-3` | M1, M3 |

## Architecture and Lifecycle

Ingress retains its current provider/invocation visibility classification. An ordinary
Discord input may therefore create hidden checking Work without a provider Tracker.

During the canonical `continue` mutation:

1. validate the requested or retained task list;
2. require at least one unfinished task;
3. promote `hidden` visibility to `visible`;
4. commit the updated title, task list, desired progress, and revisions; and
5. plan the normal Tracker create or update from the resulting complete snapshot.

The visibility change is part of the same Toolkit State mutation and state revision as
the Todo update. No second mutation, event, label, or provider observation becomes an
authority.

Explicit-invocation promotion remains available through `ensure_active_work`.
Whichever trigger promotes first wins monotonically; later hidden classifications do
not demote the cycle.

## Provider Presentation

The existing Discord progress lowerer and delivery lifecycle remain unchanged. A newly
promoted Work without a projection plans `PROGRESS_CREATE`. Existing, failed, unknown,
deleted, or confirmed-missing projections follow their current update/replacement
rules.

The Tracker continues to expose `View session` and the signed Binding-scoped
`Conversation settings` action. No settings-only message is restored.

## Failure, Retry, and Recovery

The canonical Work transaction commits before the one-attempt provider mutation.
Provider failure or ambiguity does not roll back tasks or visibility. Existing
projection status and later progress transitions retain their current bounded
reconciliation behavior.

Gateway and Agent Worker restart recovery continue reading the durable Work visibility,
desired progress, and provider projection identity. No migration is required because
the existing `hidden | visible` state model already represents the result.

## Test Strategy

### E2E primary verification

The required Discord quiet-work scenario is changed to prove:

- an unmentioned all-messages input starts Work;
- the Agent publishes an unfinished Todo list;
- one Activity Tracker appears with the current tasks and both actions;
- typing remains active;
- Gateway restart restores typing;
- a later explicit mention does not create a duplicate Tracker identity; and
- no settings-only delivery appears.

The existing deterministic Discord provider fake supplies sanitized Tracker identity,
action, typing snapshot, and delivery-category evidence. No live credentials or new
fixture are required.

### Backend verification

- A hidden active Work with unfinished tasks promotes to visible and plans one progress
  create.
- A replacement cycle with unfinished tasks is visible even when the prior finished
  cycle was hidden.
- Initial hidden checking Work still plans no Tracker.
- Existing explicit-mention promotion, visible update, cleanup, and projection tests
  remain regression gates.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Hidden task-bearing `continue` suppresses every progress effect | `tracker-260829/REQ-1`, `REQ-2` | same mutation promotes visible and plans normal create/update | Channel Work direct-action transition | focused repository test asserts visible state and progress create |
| E2E assertion that unmentioned Todo Work has zero Trackers | `tracker-260829/REQ-1` | one-identity Tracker plus active typing evidence | required Discord External Channel scenario | E2E asserts one create, one message identity, both actions |
| Initial hidden checking behavior | None; retained | `tracker-260829/REQ-3` | ingress and initial-progress planning | existing hidden initial-progress tests remain |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Initial non-mention checking Work may remain hidden, while canonical unfinished Todo publication promotes the cycle to visible | `tracker-260829/REQ-1`, `REQ-3` | `required` |
| M2 | Promotion occurs in the same Channel Work mutation before ordinary progress effect planning | `tracker-260829/REQ-1`, `REQ-2`; current Work source-of-truth architecture | `derived` |
| M3 | Existing projection identity, replacement, cleanup, typing, settings, Slack, and Scheduled Task lifecycles remain unchanged | `tracker-260829/REQ-2`, `REQ-3`; current External Channel Specs | `existing` |

## Authority Audit

- Every Requirement maps to a material mechanism and deterministic evidence.
- Canonical task state is the only promotion authority added by this snapshot.
- No optional behavior, second source of truth, provider-derived task state, or
  compatibility fallback is introduced.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

- The `continue` transition already validates unfinished tasks and owns visibility,
  desired progress, revisions, and effect planning.
- Promotion can occur before the existing hidden-effect suppression check without a
  second transaction.
- Existing provider projection and E2E fake evidence distinguish one create, one
  message identity, updates, actions, and settings-only absence.

Feasibility result: **feasible for Design revision 1**.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-08-29`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3`
- Approved scope: Show one Discord conversational Activity Tracker when an Agent
  publishes unfinished Todo work after a non-mention input, preserve lightweight
  initial checking, typing and existing Tracker actions/lifecycle, and ship the
  correction without further intermediate approval stops.
