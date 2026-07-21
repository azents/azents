---
title: "Persist Requested and Resolved AgentRun Provenance Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: provenance-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0117-agent-run-inference-provenance.md"
---

# Persist Requested and Resolved AgentRun Provenance Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `provenance-260710`
- Source: `docs/azents/adr/provenance-260710-inference-provenance.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

A per-prompt target is durable intent, while the provider/model selected at run start is execution fact. Agent target configuration and future routing policy can change after execution, so reconstructing historical resolution from current Agent state is not reliable. Resolution failures also need an AgentRun record even though no physical model snapshot exists.

One AgentRun can consume multiple FIFO user messages. A user message can later participate in another AgentRun through manual retry, while automatic retries remain attempts inside the same run. A single foreign key on either side cannot represent these relationships accurately.

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
