---
title: "Judgment-relative Routine Checks Requirements"
created: 2026-10-19
implemented: 2026-10-19
tags: [routine, scheduler, reliability]
document_role: primary
document_type: requirements
snapshot_id: routinecadence-261019
---

# Judgment-relative Routine Checks Requirements

- Snapshot: `routinecadence-261019`
- Document reference: `routinecadence-261019/REQ`

## Problem

Routine source checks and the minimum action delay currently use different clock
references. A source opportunity a few seconds before action eligibility is
retained without judgment, then waits for another complete source interval. A
nominal thirty-minute check can therefore become an approximately hourly check.

## Primary System Outcome

After a Routine judgment finishes, the Session's next regular checking
opportunity follows that completion by thirty minutes, without waiting another
full interval because of the previous judgment's processing latency.

## Supporting Scenarios or Effects

- Independent Sessions retain their own checking times.
- A restart or failed source-dispatch attempt retains recoverable checking state.
- Selected Routine work remains ordinary Session work and does not control the
  checking clock by its eventual completion time.

## Goals

- Preserve a thirty-minute checking delay measured after judgment.
- Eliminate the demonstrated seconds-short, full-interval skip.
- Retain the common Scheduler as the scheduling mechanism.

## Non-Goals

- Exact wall-clock cron execution or hard real-time deadlines.
- A separate Routine scheduler, execution owner, timer service or retry loop.
- Changes to model decisions, permissions, notifications, usage accounting,
  frontend behavior, public APIs or Scheduled Task product semantics.
- Merging, deployment, release or production-state changes.

## Requirements

### REQ-1. Judgment-relative next check

A settled judgment establishes the next regular checking opportunity thirty
minutes later, independently of the completion of any selected work.

**Acceptance criteria**

- Given a source check at T and a settled judgment at T plus seven seconds, the
  next check is not deferred until T plus sixty minutes by a separate time gate.
- Completed no-action and failed judgments remain distinguishable and retain
  normal later-check recovery rather than immediate repeated model calls.
- Earlier ordinary Session work and incomplete Routine work retain their
  existing FIFO and selection boundaries.

### REQ-2. Shared scheduling and durable recovery

Routine checks continue through the common Scheduler and existing Session owner.

**Acceptance criteria**

- Sessions with different due times do not postpone one another by a full
  thirty-minute interval.
- Existing cancellation, Stop, archive, owner fencing, source retention and
  duplicate-admission protection remain effective.
- Restarting the scheduler does not require an in-memory Routine timer to restore
  future checks.
- Other registered scheduler tasks retain their existing scheduling behavior.

### REQ-3. Verifiable bounded change

The correction is independently reviewable and does not alter unrelated work.

**Acceptance criteria**

- Deterministic clock-boundary tests reproduce the original timing failure and
  verify consecutive action, no-action, failure and queued-work cases.
- Representative assembled-product Routine E2E and full PR CI pass, including
  existing duration and asynchronous checks.
- No threshold relaxation, omitted behavioral coverage or manual success status
  is used to satisfy validation.

## Fixed Constraints

- Use the existing common Scheduler and ordinary Session Worker.
- Keep the thirty-minute delay; do not shorten it to conceal the timing gap.
- Keep existing persisted definitions and admitted work intact.
- No new versioning mechanism or production operations.

## Open Assumptions

- Existing scheduler polling and normal FIFO load can add execution latency;
  thirty minutes is an eligibility boundary, not an exact delivery deadline.

## Confirmation

The requester explicitly requested implementation of judgment-followed schedule
adjustment on 2026-10-19 and confirmed the existing common Scheduler boundary.
This snapshot records that bounded outcome. The requester subsequently approved
the disclosed shared Scheduler next-time extension and earliest-Session schedule
on the same date before implementation.
