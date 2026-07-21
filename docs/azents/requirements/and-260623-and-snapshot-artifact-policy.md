---
title: "Release and Snapshot Artifact Policy Historical Requirements Reconstruction"
created: 2026-06-23
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: and-260623
historical_reconstruction: true
migration_source: "docs/azents/adr/0072-release-and-snapshot-artifact-policy.md"
---

# Release and Snapshot Artifact Policy Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `and-260623`
- Source: `docs/azents/adr/and-260623-and-snapshot-artifact-policy.md`
- Historical source date basis: `2026-06-23`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents is moving from a private SaaS-oriented deployment model to an open-source project that publishes user-facing artifacts. The previous single-branch automatic deployment model is not enough for an open-source ecosystem because it conflates three different concerns:

- public releases that external users may install and rely on,
- public release candidates that external users may test before a stable release,
- short-lived internal snapshots for active dogfooding and development-server deployment.

The build graph can remain shared, but the release identity, artifact visibility, retention, and deployment ownership must differ by channel.

This ADR records the release and CD artifact policy only. It intentionally does not decide the full GitHub Actions migration plan, PR CI policy, open-source contribution CI security model, or branch protection rules. Those remain follow-up design topics.

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
