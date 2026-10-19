---
title: "Automatic Routine Tick Adjustment Design"
created: 2026-10-20
implemented: 2026-10-20
tags: [agent, routine, frontend]
document_role: primary
document_type: design
snapshot_id: cadenceauto-261020
---

# Automatic Routine Tick Adjustment

This bounded follow-up implements the direct request in
[cadenceauto-261020/REQ](../requirements/cadenceauto-261020-auto-raise-tick.md)
using [ADR-D1](../adr/cadenceauto-261020-auto-raise-tick.md).

## Design Authority

Revision: 1.

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Normalize a supplied delay with the effective tick after locking and refreshing the Agent, then save both atomically | REQ-1, REQ-3, ADR-D1 | required |
| M2 | Raise the form tick on valid delay edits, without lowering it or filling invalid input | REQ-2 | required |
| M3 | Retain migration, defaults, scalar bounds, permissions and tick-only rejection | REQ-3, REQ-4 | existing |

## Implementation and Feasibility

The existing repository operation already owns the current Agent lock, merged
pair validation and atomic update. When minimum delay is present, derive tick
from the supplied tick or locked current value and the new delay before the
existing pair check. Do not mutate the caller's patch dictionary. The API returns
the persisted normalized pair. The form sets both fields together on valid
whole-minute delay edits and explains automatic raising in localized copy.
Create-time validation is unchanged. No schema or migration changes are needed.

## Removal and Replacement

Replace the rejection expectation for delay-supplying inverted updates with
automatic raising (REQ-1). Retain tick-only rejection and strict scalar tests
(REQ-3). Update current specs and form copy; retain the prior implemented
snapshot and migration unchanged.

## Test Strategy

Extend the existing public Agent CRUD E2E for delay-only raising, lowering without
tick reduction and subsequent tick-only rejection. Use repository tests for
partial/paired input matrices and real PostgreSQL lock contention for both
write orders. Component play tests verify raising, non-decreasing tick and
manual tick-only invalid input. Existing E2E fixtures suffice; no new credentials
or seeded product writes are required. Preserve local logs and new-commit CI
artifacts; skips and failures remain visible. No unchanged-SHA repeat is planned.

## Design Approval

Revision 1, authority IDs M1, M2, M3 implement the requester's explicit automatic
update direction on 2026-10-20 KST. All mechanisms are required or existing; no
unresolved material technical or product decision remains.
