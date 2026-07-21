---
title: "Atomically Activate the Resolved Run and Session Profile Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: atomic-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0121-atomic-run-profile-activation.md"
---

# Atomically Activate the Resolved Run and Session Profile Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `atomic-260710`
- Source: `docs/azents/adr/atomic-260710-atomic-profile-activation.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

AgentSession last-used target and effort drive later implicit execution and Composer initialization. Updating them when input is enqueued would let unresolved or invalid intent replace the last successful profile. Waiting until run completion would leave session state stale after the model has already begun executing and make long runs inconsistent with later implicit work.

AgentRun resolved provenance, effective context limits, and running state must describe the same activation point. Starting the provider call before those writes commit could produce model output without durable execution provenance.

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
