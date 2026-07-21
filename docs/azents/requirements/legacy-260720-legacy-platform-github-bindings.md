---
title: "Retire Legacy Platform GitHub App Bindings Historical Requirements Reconstruction"
created: 2026-07-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: legacy-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0175-retire-legacy-platform-github-bindings.md"
---

# Retire Legacy Platform GitHub App Bindings Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `legacy-260720`
- Source: `docs/azents/adr/legacy-260720-legacy-platform-github-bindings.md`
- Historical source date basis: `2026-07-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-193) introduced nullable Platform GitHub App identity bindings so an installation that existed before identity binding could be claimed or reconnected safely. That transition state added nullable installation rows, nullable encrypted Toolkit credential fields, Admin claim-or-leave decisions, Public reconnect reasons, and Main Web guidance.

The deployment has one Platform GitHub App installation and no pre-binding installations. Continuing to retain that transition state makes the product appear broken and leaves supported behavior coupled to a migration path that no longer exists.

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
