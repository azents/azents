---
title: "Open Source CI Policy Historical Requirements Reconstruction"
created: 2026-06-23
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: open-260623
historical_reconstruction: true
migration_source: "docs/azents/adr/0073-open-source-ci-policy.md"
---

# Open Source CI Policy Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `open-260623`
- Source: `docs/azents/adr/open-260623-open-source-ci-policy.md`
- Historical source date basis: `2026-06-23`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents is becoming a public open-source repository. CI must therefore serve two goals at the same time:

- give contributors fast, deterministic feedback on pull requests,
- avoid exposing trusted infrastructure, secrets, write tokens, or private deployment systems to untrusted pull request code.

The release and snapshot artifact policy is recorded separately in [and-260623/ADR](and-260623-and-snapshot-artifact-policy.md). This ADR covers CI only: runner selection, required checks, path filtering, pull request safety, and workflow trigger boundaries. Snapshot publishing, external release creation, downstream deployment, and artifact retention remain governed by [and-260623/ADR](../adr/and-260623-and-snapshot-artifact-policy.md).

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
