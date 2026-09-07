---
title: "Silent Discord Scheduled Task Tracker Design"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-07
tags: [discord, scheduled-task, external-channel, activity-tracker, backend]
document_role: primary
document_type: design
snapshot_id: scheduled-260907
---

# scheduled-260907/DESIGN: Silent Discord Scheduled Task Tracker

- Snapshot: `scheduled-260907`
- Document reference: `scheduled-260907/DESIGN`
- Requirements:
  [`scheduled-260907/REQ`](../requirements/scheduled-260907-silent-discord-tracker.md)
- Decisions:
  [`scheduled-260907/ADR`](../adr/scheduled-260907-silent-discord-tracker.md)

## Current Behavior and Gap

Discord message creation receives a `suppress_notifications` option from the External
Channel Action delivery boundary. The current expression enables it for
`PROGRESS_CREATE` except when the payload identifies a Scheduled Task Tracker.

Scheduled Task run Trackers use that exact operation and payload marker, so they are
the only progress-host creations that intentionally bypass notification suppression.

## Requirement and Decision Traceability

| Requirement | Decisions | Mechanisms |
| --- | --- | --- |
| `scheduled-260907/REQ-1` | D1 | M1, M2 |
| `scheduled-260907/REQ-2` | D1 | M1, M3 |
| `scheduled-260907/REQ-3` | D1 | M1, M3 |

## Architecture and Ownership

Scheduled Task cycle state, provider projection identity, and effect planning remain
unchanged. The existing Discord provider operation is the sole notification-policy
input at message creation.

## Discord Delivery

The Discord `create_message` call sets `suppress_notifications` to true whenever the
target operation is `PROGRESS_CREATE`. It no longer inspects `tracker_kind` for this
decision.

`CONTROL_MESSAGE` registration and deletion notices and `REPLY` progress or terminal
messages continue passing false. `PROGRESS_UPDATE` remains an edit and has no create
notification option.

## Failure, Recovery, and Compatibility

Notification suppression changes only one provider request flag. Existing validation,
operation keys, authority revalidation, failure classification, settlement, and
best-effort recovery remain unchanged. No schema, API, configuration, or migration
change is required.

## Test Strategy

### Primary verification

The focused Discord delivery test verifies that Scheduled Task
`PROGRESS_CREATE` requests notification suppression while `PROGRESS_UPDATE` retains
the existing update contract. Registration and deletion control-message tests verify
they remain notification-bearing.

The pinned Discord SDK test already verifies that a true suppression input maps to the
provider message flag. The current required Scheduled Task E2E is Session-only and has
no External Channel Binding, so it cannot observe a Discord provider message. No new
live credential test is required for this provider-request flag change.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Scheduled Task Tracker `PROGRESS_CREATE` bypasses notification suppression | `scheduled-260907/REQ-1`, ADR-D1 | every Discord progress-host creation is silent | External Channel Discord create delivery | focused delivery assertion and exception absence search |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Derive notification suppression solely from Discord `PROGRESS_CREATE` | `scheduled-260907/REQ-1`, `REQ-2`, ADR-D1 | `decided` |
| M2 | Preserve Scheduled Task Tracker content, controls, update, and cleanup | `scheduled-260907/REQ-1`; current Scheduled Task and External Channel Specs | `existing` |
| M3 | Preserve non-Tracker publications and delivery failure contracts | `scheduled-260907/REQ-2`, `REQ-3`; current Specs | `existing` |

## Authority Audit

Every requirement maps to an authorized mechanism. The operation-based flag does not
change provider effect ownership or introduce another notification policy authority.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

- Scheduled Task Tracker creation already reaches the shared Discord
  `PROGRESS_CREATE` branch.
- The Discord SDK adapter already accepts and tests notification suppression.
- Registration and deletion use `CONTROL_MESSAGE`, and replies use `REPLY`, so their
  current notification behavior remains isolated.
- No persisted data or generated API surface changes.

Feasibility result: **feasible for Design revision 1**.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-09-07`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3`
- Approved scope: Suppress notifications for Discord Scheduled Task Activity Tracker
  message creation while preserving all other Scheduled Task publication and delivery
  behavior.
