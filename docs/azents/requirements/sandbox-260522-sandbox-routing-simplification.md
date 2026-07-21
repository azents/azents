---
title: "Simplify Sandbox Provider Routing Historical Requirements Reconstruction"
created: 2026-05-22
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: sandbox-260522
historical_reconstruction: true
migration_source: "docs/azents/adr/0036-sandbox-provider-routing-simplification.md"
---

# Simplify Sandbox Provider Routing Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `sandbox-260522`
- Source: `docs/azents/adr/sandbox-260522-sandbox-routing-simplification.md`
- Historical source date basis: `2026-05-22`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[sandbox-260521/ADR](../adr/sandbox-260521-sandbox-control.md) introduced `SandboxProviderControl` and adopted a structure where a provider controller opens an outbound `ConnectProvider` stream to NoIntern. After implementation, production rollout repeatedly exposed these problems:

1. Provider stream is attached to a process-local store in `sandbox-control`.
2. Worker reads Redis active provider registry and performs provider selection/allocation.
3. Redis liveness record, worker allocation decision, and `sandbox-control` stream ownership became separate sources of truth.
4. During rollout/reconnect/checkpoint restore timing, worker repeatedly hit `No active sandbox provider is available`.

This cannot be solved only with TTL, heartbeat, or retry. The real problem is that the actual owner of provider-control connection differs from the owner of allocation decision.

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
