---
title: "Fifteen-Minute Wait Timeout Requirements"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, toolkit, engine]
document_role: primary
document_type: requirements
snapshot_id: wait-260726
implemented: 2026-07-26
---

# Fifteen-Minute Wait Timeout Requirements

- Snapshot: `wait-260726`
- Document reference: `wait-260726/REQ`

## Problem

An agent coordinating active descendant work cannot request one continuous wait longer than ten minutes.

## Primary Actor

An agent coordinating active descendant agents.

## Primary Scenario

The agent calls `wait` while descendants remain active and requests a fifteen-minute timeout. The call
remains valid and returns through the existing activity, not-waitable, or timeout outcomes.

## Supporting Scenarios

- A caller continues to use the default 30-second timeout.
- A timeout above fifteen minutes is rejected as invalid input.

## Goals

- Permit a maximum `wait` timeout of 900 seconds.
- Keep the timeout limit consistent in runtime validation and Web tool presentation.

## Non-Goals

- Changing the default timeout.
- Changing descendant eligibility, mailbox observation, outcomes, or polling cadence.
- Adding a new scheduling, persistence, or API mechanism.

## Requirements

### REQ-1. Fifteen-minute maximum wait

An agent can request `wait` with `timeout_seconds` equal to 900.

**Acceptance criteria**

- Runtime validation accepts 900 seconds.
- A value greater than 900 seconds is rejected.

### REQ-2. Consistent presentation validation

The chat presentation recognizes the same maximum as the runtime.

**Acceptance criteria**

- A `wait` call with 900 seconds uses the specialized wait presentation.
- A `wait` call above 900 seconds falls back to invalid-input presentation.

## Fixed Constraints

- The default remains 30 seconds.
- The inclusive lower bound remains 0 seconds.
- Existing wait outcomes and observation behavior remain unchanged.

## Open Assumptions

- No additional operational timeout cap is imposed below 900 seconds by the runtime host.

## Confirmation

Confirmed by the requester on 2026-07-26 before ADR and design decisions began.
