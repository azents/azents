---
title: "Routine Tick and Minimum Delay Design"
created: 2026-10-20
implemented: 2026-10-20
tags: [agent, routine, scheduler, frontend]
document_role: primary
document_type: design
snapshot_id: cadence-261020
---

# Routine Tick and Minimum Delay

## Current System and Scope

The current tick is Agent-owned, defaults to 30 and accepts 1..1440 minutes.
SQL discovery computes the later of last-check-plus-tick and
last-action-plus-fixed-30. Fenced admission, capture and settlement recheck their
existing boundaries. Agent create/update and the existing profile form own
settings permissions and feedback.

This bounded change follows [Requirements](../requirements/cadence-261020-routine-tick-minimum-delay.md)
and [ADR](../adr/cadence-261020-routine-tick-minimum-delay.md).

## Design Authority

Revision: 1.

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Two Agent-owned integer settings; tick 180 and minimum delay 30 defaults | REQ-1, REQ-3 | required |
| M2 | Strict scalar validation and atomic effective-pair constraint `30 <= minimum <= tick <= 1440` | REQ-2, ADR-D1 | derived |
| M3 | Minimum delay becomes `max(old tick, 30)`; new tick becomes `max(transferred minimum delay, 180)` | REQ-6, ADR-D2 | required |
| M4 | SQL discovery and existing admission/capture/settlement gates use current Agent values and existing checkpoints | REQ-4, REQ-5 | required |
| M5 | Existing Agent form/save permissions, generated clients and error feedback expose both settings | REQ-1, REQ-2, REQ-5 | derived |

## Persistence and Validation

Add `routine_min_action_delay_minutes` with non-null default 30. Update tick
default to 180. Generate a new linear Alembic migration; copy old values using
one SQL update before replacing the range constraint with the paired constraint.
Keep tick's upper bound 1440.

Create rejects invalid complete pairs. Partial update acquires the existing
Agent `FOR NO KEY UPDATE` fence, combines supplied values with persisted ones
and rejects invalid pairs as an existing client validation error. A database
constraint remains the final authority against direct or concurrent writers.
No retries or outside I/O are added inside transactions.

The migration runs before new application code. Application rollback can
retain the additive column; schema downgrade removes it and restores old
tick range/default, retaining current tick values rather than inventing a
historical-value recovery log.

## Runtime and User Interface

Replace fixed action-delay use at due selection and all existing final
admission checks with the current Agent minimum delay. Keep tick's current
checkpoint semantics. Queued work remains queued; current eligibility checks
continue to apply without restarting work. The 30-minute scheduler discovery
cap, Stop, FIFO, occurrence exclusion, Judge, completion and notification
semantics stay unchanged.

The existing form adds one adjacent minimum-delay input and changes tick's
default/lower bound. It validates the pair without silently changing either
input and retains failed input and existing save feedback. Localized copy
explains both references and the inequality. Generated API clients carry the
new field; no handwritten transport fallback.

## Removal and Replacement

| Obsolete behavior | Authority | Replacement | Boundary and verification |
| --- | --- | --- | --- |
| Fixed minimum action delay used as runtime setting | REQ-1, REQ-4 | Current Agent minimum delay | Search all fixed-delay call sites; boundary tests |
| Tick 1-minute floor and 30-minute new-row default | REQ-2, REQ-3 | Tick minimum 30/default 180 | API/DB/UI validation and migration tests |
| Single-setting form contracts and generated surfaces | REQ-1, M5 | Paired fields and validation | Regenerate clients; component/type/API tests |

Existing implemented snapshots remain immutable; update Living Specs separately.

## Test Strategy

Extend the existing real Agent CRUD/permission E2E journey for two defaults,
paired save/read, omitted-field preservation and invalid effective pairs.
Retain the existing Routine assembled-product journey. Use narrower PostgreSQL
integration tests for migration examples 1/29/30/60/180/240/1440, exact timing
boundaries, Agent isolation, changed settings after discovery and concurrent
partial writes. Component contracts cover empty/fractional/range/inverted
inputs, stored values and existing save feedback. No new external credential
snapshot or fixture-only product write is needed.

Run backend/TypeScript quality checks, client generation, migration tests,
focused E2E and full configured CI. Preserve artifacts and report skips/failures
honestly. Do not merge, release or deploy.

## Feasibility and Risks

The existing Agent record, mutation fence and settings flow can own both values.
Existing timing paths already separate last-check and last-action references;
no new state machine is required. The one-time data transition is bounded by
existing 1..1440 values. More than one input can be submitted atomically by the
existing save. Main risk is missed final gate or an update validated against a
stale pair; integration and concurrency coverage address those boundaries.

## Design Approval

Mode: Autonomous, scoped to the requested change and boundary resolution.
Decision owner: dedicated technical interviewee `tick-design-owner`.
Revision 1 authority IDs: M1, M2, M3, M4, M5.
Approved on 2026-10-20 after the dedicated read-only authority and feasibility
review. The decision owner approved revision 1 and exactly M1, M2, M3, M4, M5.
The requester explicitly asked to implement and delegated boundary resolution.
