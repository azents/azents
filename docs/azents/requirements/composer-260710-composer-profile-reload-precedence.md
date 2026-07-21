---
title: "Restore the Latest Composer Profile Intent on Reload Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: composer-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0113-composer-profile-reload-precedence.md"
---

# Restore the Latest Composer Profile Intent on Reload Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `composer-260710`
- Source: `docs/azents/adr/composer-260710-composer-profile-reload-precedence.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

AgentSession last-used profile fields update only after successful run-start resolution. A user can select and submit a different profile while that input remains queued, or select another profile in an unsent local Composer draft. Reloading from only the last successfully resolved session profile would revert the Composer to an older selection and misrepresent the user's latest intent.

Updating the AgentSession fields at enqueue time would preserve the UI selection but corrupt their meaning when resolution later fails. Local drafts also need to retain the profile selected for their unsent prompt independently of server state.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
