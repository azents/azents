---
title: "Testenv Devtools Extension — Upgrade TC-LCY-002/003/004 to Live Historical Requirements Reconstruction"
created: 2026-04-16
implemented: 2026-04-16
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: testenv-260416
historical_reconstruction: true
migration_source: "docs/azents/design/testenv-devtools-tc-live-upgrade.md"
---

# Testenv Devtools Extension — Upgrade TC-LCY-002/003/004 to Live Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `testenv-260416`
- Source: `docs/azents/design/testenv-260416-testenv-devtools-live-upgrade.md`
- Historical source date basis: `2026-04-16`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

In Phase 1 (#2609) testenv QA, three scenarios TC-LCY-002 / 003 / 004 were closed as **audit-only PASS**. Their blockers:

| TC | Blocker | Resolution |
|---|---|---|
| TC-LCY-002 | No path to externally inject `SessionMessageKind.RESUME` into broker | Testenv API: broker inject endpoint |
| TC-LCY-003 | Cannot backdate `last_activity_at` + trigger cleanup | Minimize idle timeout / cleanup interval with config override + wait real time |
| TC-LCY-004 | Cannot inject recording hook with `get_lifecycle_hooks` DI override | Testenv API: recording hook flag + event query endpoint |

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Production admin API extension (testenv-only)
- Actual lifecycle hook handler implementation (Phase 2+)
- Durable workflow introduction (Phase 3)
- Snapshot / hibernation (Phase 4)
- DB-write-capable testenv API (structurally excluded)

## Non-goals

- Production admin API extension (testenv-only)
- Actual lifecycle hook handler implementation (Phase 2+)
- Durable workflow introduction (Phase 3)
- Snapshot / hibernation (Phase 4)
- DB-write-capable testenv API (structurally excluded)

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
