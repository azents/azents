---
title: "Project Compact Inference Summaries with User Messages Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: inline-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0122-inline-user-message-inference-summary.md"
---

# Project Compact Inference Summaries with User Messages Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `inline-260710`
- Source: `docs/azents/adr/inline-260710-inline-message-inference-summary.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[message-260710/ADR](../adr/message-260710-message-profile-provenance-display.md) makes the requested target label beside user-message sent time interactive. Its detail surface needs requested effort, latest run resolution, and safe failure information. Fetching that data only after hover or tap would introduce visible loading, per-message requests, and client cache coordination. Returning complete internal AgentRun snapshots would expose irrelevant integration/catalog diagnostics and unnecessarily enlarge history payloads.

A user message can be associated with several runs through manual retry, but the compact chat interaction needs the latest attempt by default rather than full audit history.

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
