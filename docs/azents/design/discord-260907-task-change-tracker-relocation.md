---
title: "Discord Task-Change Tracker Relocation Design"
created: 2026-09-07
updated: 2026-09-07
implemented: 2026-09-07
tags: [discord, external-channel, activity-tracker, backend, testenv]
document_role: primary
document_type: design
snapshot_id: discord-260907
---

# discord-260907/DESIGN: Discord Task-Change Tracker Relocation

- Snapshot: `discord-260907`
- Document reference: `discord-260907/DESIGN`
- Requirements:
  [`discord-260907/REQ`](../requirements/discord-260907-task-change-tracker-relocation.md)
- Decisions:
  [`discord-260907/ADR`](../adr/discord-260907-task-change-tracker-relocation.md)

## Current Behavior and Gap

Discord currently relocates progress whenever one Action contains both a reply and any
progress change. It removes the current Tracker and attaches the latest Tracker to the
final delivered reply through a transient reply-identity dependency. State-only
progress edits that host in place.

This makes routine conversational updates visibly attach and detach Tracker
presentation even when the ordered tasks are unchanged. Notification-suppressed
standalone creation makes a simpler task-change policy feasible.

## Requirement and Decision Traceability

| Requirement | Decisions | Mechanisms |
| --- | --- | --- |
| `discord-260907/REQ-1` | D1, D2 | M1, M2, M3 |
| `discord-260907/REQ-2` | D1 | M1, M4 |
| `discord-260907/REQ-3` | D2 | M2, M3, M5 |
| `discord-260907/REQ-4` | existing boundaries | M5, M6 |

## Architecture and Ownership

Canonical Channel Work continues to own the current typed ordered tasks, desired
progress, monotonic desired revision, and provider projection observation. Discord
messages remain derived provider state.

The Action transition compares an explicitly supplied task tuple with the canonical
pre-transition tasks before assigning the next desired progress. The comparison result
is process-local planning input and adds no persisted counter or relocation state.

Toolkit State remains schema version 5. Its `standalone | reply` host classification
continues to describe current provider state during lazy convergence from the previous
behavior.

## Direct Action Planning

Reply effects are planned first under the existing delivery rules.

For Discord progress with a changed task snapshot:

1. render the complete latest Tracker;
2. plan removal of the current host when one has a usable provider identity;
3. plan notification-suppressed standalone creation, dependent on confirmed removal;
4. omit removal and create directly when no current host identity exists.

The new create effect never depends on or consumes a reply provider identity. A
reply-hosted current Tracker uses its existing detach mutation for step 2.

For Discord progress with unchanged tasks, the existing create-or-update planner
retains the current host. A title-only update or identical task replacement edits a
standalone host completely or a reply host partially. A missing projection creates a
standalone Tracker.

Slack planning remains unchanged.

## Effect Execution and Settlement

The executor retains ordered delivered-effect dependencies only for remove-before-
create behavior. The transient provider-message identity dependency and result-key
substitution introduced for reply attachment are removed.

Progress effects retain exact Work-cycle and desired-revision revalidation immediately
before provider I/O. Settlement records `standalone` for replacement creation and the
current host kind for removal. Confirmed removal clears the old identity before
replacement creation settles the new standalone identity.

One service instance continues to serialize complete Actions for the same Binding.
Different Bindings remain independent, and the existing Session owner-generation
fence remains the cross-Worker execution boundary.

## Failure and Recovery

- Reply failure does not prevent task-change relocation because tasks, not reply
  delivery, determine movement.
- Removal failure or ambiguity skips dependent standalone creation and retains the
  known current host observation.
- Standalone creation failure after confirmed removal records failed projection state
  without a provider identity.
- A later progress change uses the persisted observation to update the retained host
  or create a missing standalone Tracker with the complete latest snapshot.
- No durable retry, outbox, provider replay, or compensation record is added.

## Migration, Rollout, and Rollback

No schema migration is required. Existing standalone hosts continue normally. Existing
reply hosts remain readable and receive in-place updates while tasks are unchanged.
Their next task change detaches the reply presentation and creates a standalone host.

Rollback restores reply-host relocation without data conversion because schema version
5 and host classification remain unchanged.

## Observability

Existing ordered provider outcomes expose reply, Tracker removal, and standalone
creation results. Dependency skips retain the bounded
`effect_dependency_not_delivered` outcome. No counter, timer, or new durable telemetry
is introduced.

## Test Strategy

### E2E primary verification

Update the required Discord External Channel journey to verify:

- initial Tracker creation is notification-suppressed and standalone;
- a changed task snapshot delivers any reply, removes the current Tracker, and creates
  one new standalone Tracker afterward;
- an identical task replacement keeps the same Tracker message identity;
- a title-only update keeps the same Tracker message identity;
- a reply-only Action leaves Tracker identity and content unchanged;
- final cleanup removes a standalone Tracker without changing the final reply.

The deterministic Discord provider fake supplies create, edit, delete, notification
suppression, content, Embed, and component evidence. No live credentials are required.

### Backend verification

- complete typed task equality controls Discord relocation;
- task changes plan reply, optional remove, and standalone create in order;
- replacement creation depends on removal but not reply delivery;
- unchanged tasks preserve standalone and reply hosts;
- removal failure skips creation;
- create failure settles recoverable missing projection state;
- Slack planning remains unchanged;
- same-Binding serialization and stale revision rejection remain covered.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Any reply plus progress change relocates the Discord Tracker | `discord-260907/REQ-1`, `REQ-2`, ADR-D1 | exact task-snapshot change trigger | direct Action planning | repository tests |
| Newly relocated Trackers attach to the final reply | `discord-260907/REQ-1`, ADR-D2 | notification-suppressed standalone creation | repository and Discord effect planning | repository and E2E evidence |
| Progress effects can consume a transient prior reply identity | `discord-260907/REQ-1`, ADR-D2 | remove-before-create delivered dependency only | effect-plan contract and executor | type search and executor tests |
| Reply-host update and detach support | existing schema version 5 state; `discord-260907/REQ-2` | retained for lazy convergence and cleanup | Discord delivery adapter | reply-host compatibility tests |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Compare explicitly supplied complete tasks with canonical pre-transition tasks | `discord-260907/REQ-1`, `REQ-2`, ADR-D1 | `decided` |
| M2 | Task changes remove the current Discord Tracker before replacement | `discord-260907/REQ-1`, `REQ-3`, ADR-D2 | `decided` |
| M3 | Replacement is a notification-suppressed standalone Tracker independent from reply identity | `discord-260907/REQ-1`, ADR-D2 | `decided` |
| M4 | Unchanged-task progress retains and updates the current host in place | `discord-260907/REQ-2`, ADR-D1 | `required` |
| M5 | Immediate best-effort dependencies, recovery, and desired-revision fencing remain | `discord-260907/REQ-3`, `REQ-4`; current External Channel Specs | `existing` |
| M6 | Same-Binding process-local serialization and unaffected provider behavior remain | `discord-260907/REQ-4`; current External Channel Specs | `existing` |

## Authority Audit

Every requirement maps to an authorized material mechanism. Task equality introduces
no second progress authority because it is derived from the canonical pre-transition
and requested typed snapshots. Standalone replacement and reply-identity removal are
fully determined by accepted ADR decisions.

Authority result: **pass for Design revision 1**.

## Feasibility Validation

- Canonical Work already retains the complete typed task list required for equality.
- Provider effect planning already supports ordered dependencies and standalone
  notification-suppressed creation.
- Current host classification safely distinguishes standalone deletion from reply
  detachment.
- Same-Binding serialization and exact desired-revision validation already cover
  overlapping Actions and stale queued effects.
- No schema, provider API, configuration, or distributed coordination change is
  required.

Feasibility result: **feasible for Design revision 1**.

## Design Approval

- Mode: `Collaborative`
- Decision owner: `requester`
- Approved on: `2026-09-07`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6`
- Approved scope: Relocate Discord Activity Trackers only when the complete ordered
  task snapshot changes, recreate them as silent standalone messages after removing
  the current host, and retain current host position when tasks are unchanged.
