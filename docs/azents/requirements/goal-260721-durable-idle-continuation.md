---
title: "Durable Goal Idle Continuation Requirements"
created: 2026-07-21
implemented: 2026-07-21
tags: [goal, backend, worker]
document_role: primary
document_type: requirements
snapshot_id: goal-260721
---

# Durable Goal Idle Continuation Requirements

- Snapshot: `goal-260721`
- Document reference: `goal-260721/REQ`

## Problem

A Worker shutdown can race with a completed run before its session-idle lifecycle is processed. An active Goal then loses the automatic continuation that the completed run should have caused.

## Primary Actor

A user with an active session-scoped Goal.

## Primary Scenario

A user's run completes while its Worker is shutting down. Another Worker later owns or recovers the session. After already pending user or system work has been processed and the session reaches idle, the active Goal continues exactly once for the completed run.

## Supporting Scenarios

- A graceful handover observes a completed run after the shutdown signal.
- Stuck-session recovery resumes a session after a process loss at the completed-run boundary.
- A queued wake-up or pending input delays continuation until existing work is exhausted.

## Goals

- Preserve automatic continuation for active Goals across Worker handover and recovery.
- Preserve existing ordering: pending work runs before a Goal continuation.
- Prevent duplicate Goal continuation for one completed run across retries, redelivery, handover, and recovery.

## Non-Goals

- Create continuation for failed, stopped, interrupted, or cancelled runs.
- Retroactively repair continuations missed before this capability is deployed.
- Change continuation behavior for paused, blocked, complete, or empty Goals.

## Requirements

### REQ-1. Durable completed-run continuation obligation

When a completed run reaches its terminal boundary, the session retains the obligation to evaluate idle continuation until that obligation has been consumed, even if the owning Worker stops.

**Acceptance criteria**

- A Worker shutdown at or immediately after completed-run terminalization cannot discard the continuation obligation.
- A subsequent Worker can discover and process the obligation without relying on the prior Worker's in-memory state.

### REQ-2. Ordered continuation after true idle

The continuation obligation is evaluated only after the session has no pending command, pending wake-producing input, or queued actionable wake-up.

**Acceptance criteria**

- Pre-existing user and system work executes before the Goal continuation it delayed.
- A session with active pending work does not create a premature Goal continuation.

### REQ-3. Exactly-once logical continuation

Each eligible completed run produces at most one Goal continuation evaluation outcome across redelivery, handover, and recovery.

**Acceptance criteria**

- Repeated recovery or wake-up delivery cannot enqueue duplicate Goal continuation input for the same completed run.
- An active Goal receives one continuation input after an eligible completed run reaches idle.

### REQ-4. Existing terminal-state policy

Only completed runs are eligible for this continuation behavior.

**Acceptance criteria**

- Failed, stopped, interrupted, and cancelled terminal runs do not create Goal continuation input.
- Existing Goal-state eligibility rules remain unchanged.

## Fixed Constraints

- Pending input buffers remain the durable source of truth for model-visible continuation payload.
- Broker messages remain wake-up signals rather than durable continuation payload.
- The implementation must tolerate Worker shutdown, broker redelivery, and stuck-session recovery.
- No legacy fallback or bulk repair is required.

## Open Assumptions

- Existing deployed sessions without a recorded obligation do not require backfill.

## Confirmation

Confirmed by the requester on 2026-07-21 before ADR and design decisions began.
