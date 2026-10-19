---
title: "Agent Routine Check Interval Decisions"
created: 2026-10-19
tags: [agent, routine, scheduler, architecture]
document_role: primary
document_type: adr
snapshot_id: cadence-261019
---

# Agent Routine Check Interval Decisions

## ADR-D1 — One Agent-owned interval

Accepted on 2026-10-19 by the dedicated autonomous technical interviewee
`tick-design-owner`, within the requester's design-to-PR delegation.
Authority: `cadence-261019/REQ-1` through `REQ-4`.

Use one non-null integer `routine_check_interval_minutes` on the existing Agent,
with ORM/server default 30 and a named database CHECK between 1 and 1440.
Extend the existing Agent create/read/partial-update path and regenerate clients.
Both due-time SQL and fenced admission read that same persisted value.

Rejected: a separate table or JSON overrides. These introduce another default,
ownership and validation boundary for a single required number.

The discovery cap and minimum action delay remain 30 minutes. No new timer,
settings cache, immediate wake guarantee, or per-Routine scheduling gate is added.
Changing the setting can be observed only at the next existing Scheduler pass.

Risks: shorter intervals increase judgment costs; a short interval does not bypass
minimum action delay. Admission must read current state after discovery, reject
invalid input, and preserve omission. The additive migration populates existing
Agents with 30; rolling application code back can retain the extra column.
