---
title: "Routine Tick and Minimum Delay Requirements"
created: 2026-10-20
implemented: 2026-10-20
tags: [agent, routine, scheduler, frontend]
document_role: primary
document_type: requirements
snapshot_id: cadence-261020
---

# Routine Tick and Minimum Delay

## Problem

Agent Routine checking currently exposes a configurable tick while its separate
minimum action delay is fixed at 30 minutes. The prior defaults happen to be
identical. Administrators need independently configurable values with a bounded
relationship and a less frequent default tick.

## Primary Actor and Scenario

An Agent administrator views, changes and saves the Routine tick and minimum
action delay together, then the Agent's Sessions use those settings at subsequent
eligible checking opportunities.

## Requirements

- **REQ-1:** Expose separate Agent-level whole-minute Routine tick and minimum
  action delay settings through the existing settings workflow. Reloading settings
  retains both saved values.
- **REQ-2:** Every accepted effective configuration satisfies
  `30 minutes <= minimum action delay <= tick`. Reject invalid combinations without
  silently adjusting either value. Partial updates must satisfy the same relation
  when combined with the retained value.
- **REQ-3:** The default minimum action delay is 30 minutes and the default tick is
  180 minutes (3 hours) for new Agents.
- **REQ-4:** Tick continues to govern the existing checking checkpoint. Minimum
  action delay continues to govern the separate last-action reference. Due
  selection and final admission agree on the current Agent's values. Neither value
  promises exact execution or notification times.
- **REQ-5:** Preserve existing settings permissions, save feedback, Stop, FIFO,
  queued/running work, judgment, completion and notification semantics. Settings
  changes apply at the next normal scheduler scan without cancelling current work.
- **REQ-6:** For existing Agents, transfer the previous tick into minimum action
  delay, then set the new tick to `max(minimum action delay, 180 minutes)`.
  A previous tick of 60 minutes becomes minimum delay 60 and tick 180; a previous
  tick of 240 minutes becomes minimum delay 240 and tick 240. Previous ticks
  below 30 minutes become minimum delay 30 and tick 180.

## Fixed Constraints and Non-Goals

The existing 1440-minute tick upper bound, whole-minute representation and omitted
update semantics remain unless the requester changes them. The new inequality
makes the effective tick lower bound 30 minutes and bounds minimum delay by tick.
No per-Routine override, new scheduler, immediate wake, retry policy, automatic
merge, release or deployment is requested.

## Migration Boundary

The previous contract permits ticks from 1 through 29 minutes. Directly
transferring those values conflicts with REQ-2. The complete transition is
`minimum delay = max(previous tick, 30 minutes)`, followed by REQ-6's new tick
calculation.

## Confirmation

The requester explicitly requested separate values, the inequality and defaults
on 2026-10-20 KST, then specified REQ-6's previous-tick transfer and maximum rule.
The earlier preserve-tick option was withdrawn and is not implementation
authority. The requester then explicitly delegated resolving the boundary and
proceeding through implementation without another interview. This snapshot
records the resulting complete contract. The previously implemented
cadence-261019 snapshot is immutable.
