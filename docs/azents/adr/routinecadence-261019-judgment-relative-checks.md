---
title: "Judgment-relative Routine Checks Decisions"
created: 2026-10-19
tags: [routine, scheduler, reliability]
document_role: primary
document_type: adr
snapshot_id: routinecadence-261019
---

# Judgment-relative Routine Checks Decisions

Authority: [routinecadence-261019/REQ](../requirements/routinecadence-261019-judgment-relative-checks.md).

## D1. Task-directed next execution through the common Scheduler

Accepted by the requester on 2026-10-19 after the shared-Scheduler extension was
explicitly presented. This implements REQ-1 and REQ-2.

Allow a completed system scheduler task to return a timezone-aware next execution
time. A null value retains completion time plus the existing definition interval.
The common Scheduler alone persists scheduling state and retains its existing
lease, failure policy and recovery behavior. Routine source dispatch returns the
earliest eligible Session checking time, bounded by the existing regular interval
for discovering new definitions.

Judge settlement advances the Session checking reference to settlement time.
The next eligible check is thirty minutes later, not thirty minutes after the
eventual completion of selected work. Source evidence and ordinary execution
ownership remain unchanged.

### Alternatives

- A frequent Routine-specific scan on the common Scheduler would add unnecessary
  background work and was not chosen.
- Updating only the Session checking reference leaves the global fixed-interval
  scan capable of missing the new due time by an entire interval.
- A separate timer service or Routine scheduler violates the retained shared
  scheduling boundary.

### Consequences and risks

The internal Scheduler Job Runtime result becomes a typed envelope containing
summary and nullable next execution time; all existing handlers explicitly retain
their fixed-interval behavior. Polling and serial task execution can add latency,
so this is an eligibility guarantee rather than an exact-time deadline.
Concurrent judge settlement may make an earlier scan unnecessary, but it must
not postpone the actual due time by another full interval. No new persisted
schema, scheduling owner, public API or configuration is introduced.
