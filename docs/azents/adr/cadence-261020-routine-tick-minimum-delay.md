---
title: "Routine Tick and Minimum Delay Decisions"
created: 2026-10-20
tags: [agent, routine, scheduler]
document_role: primary
document_type: adr
snapshot_id: cadence-261020
---

# Routine Tick and Minimum Delay Decisions

Authority: [cadence-261020/REQ](../requirements/cadence-261020-routine-tick-minimum-delay.md).

## Decision Map

The two Agent-owned settings, new defaults, inequality, existing-value transfer
and retained scheduling semantics are fixed by the requester. The prior
preserve-tick choice is superseded. No new scheduler, retry policy, per-Routine
authority or configuration mode is introduced.

## ADR-D1. Preserve existing admission ownership

Retain `routine_check_interval_minutes` as tick and add an Agent-owned minimum
action delay. Both values use existing create/read/update/save authority.
Serialize effective-pair validation with the existing Agent mutation fence;
the database enforces the same inequality atomically. This derives from REQ-1,
REQ-2 and REQ-5 and avoids a new settings authority.

Independent per-field validation alone is insufficient for partial or concurrent
updates. Silently clamping ordinary saves is rejected by REQ-2. Only the
requester-defined one-time existing-data transition performs normalization.

## ADR-D2. Transition from the old tick before replacing it

In one database update, derive minimum delay from the old tick with a 30-minute
floor, then derive the new tick with a 180-minute floor. Set new-row defaults
separately to minimum 30 and tick 180. Do not reset all old values to defaults or
retain the old tick as tick; both contradict REQ-6.

This introduces no versioning, compatibility fallback or new runtime mode.
