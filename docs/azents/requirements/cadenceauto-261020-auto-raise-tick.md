---
title: "Raise Routine Tick When Saving Minimum Delay"
created: 2026-10-20
implemented: 2026-10-20
tags: [agent, routine, frontend]
document_role: primary
document_type: requirements
snapshot_id: cadenceauto-261020
---

# Raise Routine Tick When Saving Minimum Delay

## Primary Actor and Scenario

An Agent administrator increases the minimum Routine action delay beyond the
current tick and saves it without having to raise the tick separately.

## Requirements

- **REQ-1:** Updating minimum delay automatically raises tick to the greater of
  the effective tick and the supplied delay. An omitted tick uses the currently
  stored tick. Lowering delay does not lower tick.
- **REQ-2:** The settings form immediately reflects a needed tick increase when
  a valid delay is edited. Existing field validation and save feedback remain.
- **REQ-3:** Tick-only updates below the stored delay remain invalid. Whole-minute
  bounds, permissions and atomic concurrent-update behavior remain unchanged.
- **REQ-4:** Preserve the existing migration and new-Agent defaults from
  [cadence-261020/REQ](cadence-261020-routine-tick-minimum-delay.md). Do not change
  the migration to equal tick and delay. Do not reorganize Agent settings.

## Confirmation and Verification

The requester explicitly requested only automatic tick updates on 2026-10-20 KST
after withdrawing the equal-value migration proposal. This is direct
implementation authority. Verify partial and paired updates, decreasing delay,
tick-only rejection, concurrent writes and the form interaction. Run changed-code
checks and the new commit's CI; do not repeat unchanged-SHA CI by default.
