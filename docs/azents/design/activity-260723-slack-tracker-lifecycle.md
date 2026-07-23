---
title: "Slack Activity Tracker Lifecycle Design"
created: 2026-07-23
updated: 2026-07-23
tags: [slack, external-channel, activity, delivery, backend, testenv]
document_role: primary
document_type: design
snapshot_id: activity-260723
---

# Slack Activity Tracker Lifecycle Design

- Snapshot: `activity-260723`
- Requirements: [`activity-260723/REQ`](../requirements/activity-260723-slack-tracker-lifecycle.md)
- ADR: [`activity-260723/ADR`](../adr/activity-260723-slack-tracker-lifecycle.md)

## Scope and Traceability

| Requirement | Decision | Mechanism |
| --- | --- | --- |
| `REQ-1` | `ADR-D2` | Binding-keyed control-message intent for one button-only Session link |
| `REQ-2` | `ADR-D1` | Deterministic status and Todo `task_card` renderer with stable task IDs |
| `REQ-3` | `ADR-D3` | Reply-first action ordering and delivered-reply delete gate |
| `REQ-4` | `ADR-D3` | Active-only replacement plus create/reply completion reconciliation |

## Presentation

`external_channel_activity` owns a deterministic provider presentation. The durable
work payload stores state and ordered task ID/title/status values, but no Session URL.
Rendering produces accessible fallback text and Slack-native blocks:

- checking or working state begins with one `task_card` whose stable ID is
  `activity-status` and whose status is `in_progress`;
- every canonical Todo becomes a separate `task_card` in order;
- pending cards omit status, in-progress cards use `in_progress`, and completed cards
  use `complete`;
- title fields remain literal strings and are not interpreted as mrkdwn;
- completed Tracker presentation is not provider-delivered because normal completion
  deletes the Tracker.

The Channel Action input accepts at most 49 tasks, leaving one of Slack's 50 message
blocks for the processing status card.

## Session Navigation

Initial binding activation computes the Session URL after Workspace, Agent, and
Session identity are available. It commits a `control_message` delivery attempt whose
origin is the binding and whose payload contains only the thread target, accessible
fallback text, and one URL button. Idempotent origin identity prevents another
Session-link attempt for the same activation. The Activity Tracker remains a separate
`progress_create` attempt owned by the invocation batch and work cycle.

Both intents commit before Slack calls. The Session link and initial Tracker are
attempted before Session wake-up so the participant sees navigation and activity when
execution begins. Provider failure remains a durable delivery outcome and does not
roll back activation.

## Work-Cycle Lifecycle

`ensure_active_work` creates checking desired state before wake-up. `continue`
replaces canonical tasks, increments desired progress revision, and updates the
retained Tracker identity. `finish` sets work to finished, clears desired Tracker
state, commits the required final reply, and commits a delete intent when the provider
identity is already known.

The action service orders reply delivery before delete delivery. Failed, unknown, or
not-attempted replies terminalize the pending delete as not attempted. A delivered
reply permits cleanup.

## Recovery and Races

A failed active update with confirmed `message_not_found` clears only the matching
provider identity and creates one replacement create intent from current desired
state. Replacement is prohibited when work is finished or desired state is absent.

A replacement create may finish after the work cycle. Conversely, the final reply may
finish while Tracker creation is still unresolved. Both completion paths inspect the
same finished action and provider identity and idempotently ensure its
`progress_delete` intent. The later completion therefore owns convergence without a
provider retry.

A Tracker delete that returns `message_not_found` has already reached the desired
absent state. The delivery ledger records the reconciled delivered outcome with a safe
already-absent reason and clears the retained provider identity. Approval-control
message deletion remains outside this work-owned reconciliation.

## API, Persistence, and Migration Impact

No public API or database schema changes are required. Existing work, action, and
delivery records carry the desired payload, stable task IDs, origin identity, and
provider message key. Generated API clients therefore do not require regeneration.

## Security and Interaction Boundary

Task cards are read-only message blocks and do not add Slack interaction callbacks.
The only URL action is the existing HTTPS Session navigation button. Credentials stay
inside provider adapters and no payload stores credentials.

## Test Strategy

### Verification matrix

| Behavior | Primary evidence | Boundary |
| --- | --- | --- |
| Native task-card payload and indicator mapping | Pure renderer tests | Exact Block Kit JSON and literal titles |
| 49-task maximum | Channel Action input-model test | Slack 50-block message constraint |
| Reply-before-delete gate | Channel Action service tests | Failed and unknown final replies never delete |
| Active-only replacement and missing delete convergence | Work repository tests | Durable work, action, and delivery rows |
| One-time Session link and initial Tracker | Event processor DB-backed test | Binding activation and idempotent origins |
| Desktop/mobile provider presentation | Live Slack or provider acceptance validation | `task_card` support and omitted-status rendering |

### Fixtures and prerequisites

Deterministic repository tests use the existing PostgreSQL test fixture. Local runs may
skip when Docker is unavailable; required CI must run them. The current fake Slack
provider does not render new task cards, so exact desktop/mobile visual evidence needs
a Slack-capable manual or automated provider-validation environment. No credential is
stored in test evidence.

### CI and acceptance

Ruff, Pyright, focused pytest, documentation validation, and required stack CI must
pass. The snapshot must not be marked implemented until Slack accepts pending task
cards with omitted status and desktop/mobile clients show no pending status indicator.
A provider rejection or unexpected pending indicator fails the acceptance check and
returns the presentation decision to the ADR stage.
