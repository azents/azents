---
title: "Judgment-relative Routine Checks Design"
created: 2026-10-19
implemented: 2026-10-19
tags: [routine, scheduler, reliability, testing]
document_role: primary
document_type: design
snapshot_id: routinecadence-261019
---

# Judgment-relative Routine Checks Design

Authority: [Requirements](../requirements/routinecadence-261019-judgment-relative-checks.md)
and [ADR-D1](../adr/routinecadence-261019-judgment-relative-checks.md).

## Design Authority

- Design revision: `1`

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | A typed task result can direct the common Scheduler's next execution time; null preserves fixed-delay behavior. | ADR-D1, REQ-2 | decided |
| M2 | Settled judgment advances the existing Session checking reference; eligibility respects both checking and action-delay boundaries. | ADR-D1, REQ-1 | decided |
| M3 | Routine dispatch returns the earliest eligible Session time, capped by its regular discovery interval. | ADR-D1, REQ-1/2 | derived |
| M4 | Existing DB leases, Session ownership, source retention, cancellation and failure recovery remain authoritative. | REQ-2, current Routine Spec | existing |

## Mechanisms and ownership

The Scheduler task result is a frozen, extra-forbidding validated model. Its
summary remains opaque observation metadata; its nullable next execution time
must be timezone-aware. The Job Runtime adapter serializes the whole result and
the Scheduler validates it on receipt. A non-null time replaces only the success
schedule; existing failure policies and leases are unchanged. A time already
passed is clamped to completion time and retried through normal polling.

Routine source selection computes each Session's next time as the later of
`last_tick_at + 30 minutes` and `last_action_at + 30 minutes`. Missing references
are ignored; neither reference means due now. Both due selection and the
earliest-time query use the same active Session/root/Agent/definition predicates.
Source admission retains its transaction-local checks and duplicate guard.

Judge settlement advances `last_tick_at` to settlement time in the same fenced
transaction as the observation/source-consumption update. This existing field is
the checking cadence checkpoint, advanced by source collection and settlement.
No-action and failed judgments advance the checking checkpoint but do not change
the independent last-action reference. Empty captures also settle normally.
No new state field, format version, migration or cleanup job is needed.

The source-only dispatcher still does not execute a model. After its bounded
pass, it reads the earliest next time. The handler returns the earlier of that
time and completion plus thirty minutes, preserving discovery of new Sessions.
An exhausted deadline or remaining due Session requests a normal next-poll pass.
Settlement racing the query can produce an early scan; that scan rereads the
current state and schedules the actual due time instead of another full interval.
Independent Sessions participate in one earliest-due schedule without changing
their own eligibility. Ordinary selected work does not reset this schedule.

## Failure, recovery and rollout

All scheduling remains in the existing scheduler-state row. Process termination
before settlement leaves its due state recoverable after lease expiry. Routine
source/broker errors retain their existing propagation, committed-input recovery
and failure interval. Model failures remain failed observations, not no-action
success. Stop/archive and stale owners retain existing fences.

Other task handlers return null next execution time and retain their old cadence.
The internal adapter/result cutover is deployed as one code revision through the
existing deployment process; no legacy-result fallback is added. No operational
deployment or manual state rewrite is part of this change. Rollback retains
readable existing Toolkit State and definitions.

## Removal and Replacement

| Existing behavior | Removal authority | Replacement | Boundary | Verification |
| --- | --- | --- | --- | --- |
| Every successful scheduler handler result is an opaque summary only. | ADR-D1 | Typed summary/next-time envelope | All scheduler handlers, adapter, service and tests | Constructor audit, strict typecheck and adapter/service regressions |
| Routine dispatch always waits a full interval after an early scan. | REQ-1, ADR-D1 | Earliest eligible Session time | Source repository and handler | Clock-boundary and two-Session tests |
| Judgment settlement leaves the checking reference at the preceding source tick. | REQ-1, ADR-D1 | Advance it at fenced settlement | Judgment inbox settlement | Action/no-action/failure regression |

No public/generated API, definition, admitted context or stored-record removal.

## Test Strategy

Representative required Routine E2E remains the assembled-product primary
verification: real Scheduler, Worker, inbox, model fixtures and Runtime tools.
No external credentials or notifications to live providers are needed. Existing
Web journeys remain unchanged.

Deterministic repository tests use the existing PostgreSQL fixture and explicit
timestamps: the original seven-second skew, adjacent independent Sessions,
action/no-action/failure, queued judgments, incomplete work, Stop and recovery.
Scheduler tests cover envelope serialization, aware times, explicit override,
past time, null default, invalid results, failure and cancellation. Tests must
prove time-dependent eligibility directly, without thirty-minute sleeps, fake
success statuses or skipped coverage. Existing CI duration rules remain intact.

Verification evidence includes native pytest results, Ruff, strict typecheck,
docs validation, independent read-only review, exact PR SHA and full CI rollup.
No production failure injection or mutation is authorized.

## Feasibility

Feasible: the common Scheduler already owns `next_run_at` and a durable lease.
The Job Runtime carries validated JSON results, while Routine settlement and
state updates already share one fenced transaction. The existing nullable
timestamp state supports the new clock reference without a migration. SQL due
selection and minimum due time can share a single query projection. No new
authority owner, provider dependency or public API is required.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-10-19`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: the requester approved judge-followed thirty-minute checking
  and then explicitly approved common-Scheduler next-time support, earliest
  Session scheduling, unchanged other tasks and no separate frequent polling.
  Local typed-envelope/query/test structure is implementation detail within that
  disclosed mechanism set.
