---
title: "Agent Routine Check Interval Requirements"
created: 2026-10-19
implemented: 2026-10-19
tags: [agent, routine, scheduler, frontend]
document_role: primary
document_type: requirements
snapshot_id: cadence-261019
---

# Agent Routine Check Interval

## Primary Scenario

An Agent administrator changes how frequently the Agent's Session Routines are
considered for judgment using the existing Agent settings and save workflow.

## Confirmation and Scope

The requester explicitly delegated simple design through implementation and a
separate PR on 2026-10-19. This snapshot records that bounded intent and delegated
reversible choices; it does not authorize merging or releasing the settings PR.
The unchanged default is 30 minutes. This is a checking interval, not a guaranteed
execution or notification schedule.

## Requirements

- **REQ-1:** Agent administrators can view and save a whole-minute Routine check
  interval between 1 and 1440 minutes. New and existing Agents use 30 minutes
  unless configured. Reloading settings retains the saved value.
- **REQ-2:** Each Agent's configured interval governs the next eligible Routine
  source/judgment opportunity for its Sessions. Different Agents are independent;
  settled judgment and collected sources retain the existing checkpoint semantics.
- **REQ-3:** Omitted updates preserve the setting. Null, fractional, and out-of-range
  values fail validation. Existing settings permissions apply. Saving shows the
  existing pending/success/error feedback; failed saves do not discard input.
- **REQ-4:** Changes apply on the next regular Scheduler pass and do not cancel or
  repeat already queued or running judgments. Existing discovery latency, FIFO,
  Stop, minimum action delay, model timing decisions, accounting, completion,
  notification, and occurrence exclusion remain unchanged.
- **REQ-5:** The settings explain the default, allowed range, possible checking
  cost, and distinction from execution/notification cadence in supported locales.

## Non-goals and Assumptions

No per-Routine or per-Session override, preset system, enable toggle, cron editor,
new scheduler, guaranteed immediate checking, action-delay changes, or unrelated
settings redesign. One minute and one day are delegated safety bounds, not
claims of user research. Runtime settings edits can take up to the existing
30-minute discovery window to be observed, plus normal scheduling latency.
