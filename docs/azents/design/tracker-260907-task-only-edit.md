---
title: "Discord Task-Only Tracker Edit Design"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-07
tags: [discord, external-channel, activity-tracker, backend, testenv]
document_role: primary
document_type: design
snapshot_id: tracker-260907
---

# tracker-260907/DESIGN: Discord Task-Only Tracker Edit

- Snapshot: `tracker-260907`
- Document reference: `tracker-260907/DESIGN`
- Requirements:
  [`tracker-260907/REQ`](../requirements/tracker-260907-task-only-edit.md)
- Decisions:
  [`tracker-260907/ADR`](../adr/tracker-260907-task-only-edit.md)

## Current Behavior and Gap

The current Action planner computes exact typed task equality and recreates the Discord
Tracker whenever tasks differ. The recreation branch does not distinguish Actions with
a conversational message from message-free progress updates.

The repository already has a non-relocation create-or-update path that edits the
current standalone or reply host in place and creates a silent standalone Tracker when
the projection is missing.

## Requirement and Decision Traceability

| Requirement | Decisions | Mechanisms |
| --- | --- | --- |
| `tracker-260907/REQ-1` | D1 | M1, M2 |
| `tracker-260907/REQ-2` | D1 | M1, M3 |
| `tracker-260907/REQ-3` | D1 | M2, M3, M4 |

## Architecture and Ownership

Canonical Channel Work ownership, typed task equality, desired progress, host
classification, and provider projection settlement remain unchanged. Message presence
is transaction-local Action input and does not become persisted Tracker state.

## Direct Action Planning

The Discord recreation predicate requires all three conditions:

1. provider is Discord;
2. explicitly supplied ordered tasks differ from canonical pre-transition tasks; and
3. the Action contains a conversational message.

When the predicate is true, the existing reply-first, optional remove/detach, and
silent standalone create plan remains unchanged.

When tasks differ but the message is absent, the planner uses the existing
create-or-update path:

- a present or recoverable keyed host receives `PROGRESS_UPDATE` with its current host
  kind;
- a deleted, missing, or failed unkeyed host receives silent standalone
  `PROGRESS_CREATE`;
- no delete-and-create dependency is planned.

Slack planning remains unchanged.

## Failure, Recovery, and Concurrency

Task-only updates retain current immediate best-effort settlement. Failed or ambiguous
updates preserve their existing projection observation and are retried only by a later
explicit complete progress update. Missing-host creation retains the existing
ambiguity behavior.

Same-Binding Actions remain process-locally serialized, and every progress effect
retains exact Work-cycle and desired-revision revalidation before provider I/O. No new
durable retry, distributed lock, counter, or timer is introduced.

## Migration, Rollout, and Rollback

No schema or data migration is required. Existing standalone and reply hosts continue
to use schema-version-5 host classification. Rollback restores task-only relocation
without data conversion.

## Test Strategy

### E2E primary verification

Extend the required Discord journey so a message-associated task change recreates one
silent standalone Tracker, then a later task-only change updates that same Tracker
message identity in place.

The deterministic Discord fake supplies create, edit, delete, message identity, Embed,
and control evidence. No live credentials are required.

### Backend verification

- message plus changed tasks retains reply, remove, and standalone create planning;
- changed tasks without a message update a standalone host in place;
- changed tasks without a message update a reply host in place;
- changed tasks without a message create when no host exists;
- identical tasks and title-only changes retain current behavior;
- Slack planning remains unchanged.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Task changes always enter Discord remove-before-create relocation | `tracker-260907/REQ-1`, ADR-D1 | relocation requires the same Action to contain a message | direct Action recreation predicate | repository tests |
| Task-only delete and standalone recreate effects | `tracker-260907/REQ-1`, ADR-D1 | current-host update or missing-host create | direct Action effect plan | effect-order and E2E evidence |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Gate Discord relocation on both changed tasks and same-Action message presence | `tracker-260907/REQ-1`, `REQ-2`, ADR-D1 | `decided` |
| M2 | Route task-only changes through current-host update or missing-host create | `tracker-260907/REQ-1`, `REQ-3`, ADR-D1 | `derived` |
| M3 | Preserve message-associated task-change remove-before-create relocation | `tracker-260907/REQ-2`; current External Channel Specs | `existing` |
| M4 | Preserve best-effort recovery, same-Binding serialization, and revision fencing | `tracker-260907/REQ-3`; current External Channel Specs | `existing` |

## Authority Audit

Every requirement maps to an authorized material mechanism. Message presence is
existing Action input and does not create another source of truth. No unresolved
material choice remains.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

- The planner already receives nullable message input beside requested tasks.
- The recreation predicate is transaction-local and requires no persistence change.
- The existing generic create-or-update path already implements the required task-only
  host behavior.
- Current unit and required E2E fixtures expose effect operations and provider message
  identities needed for verification.

Feasibility result: **feasible for Design revision 1**.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-09-07`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: Keep message-free task updates on the current Discord Tracker host,
  create only when no host exists, and preserve silent standalone relocation for task
  changes that accompany a conversational message.
