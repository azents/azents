---
title: "Correlate Terminal Run Events by Run ID Historical Requirements Reconstruction"
created: 2026-07-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: terminal-260712
historical_reconstruction: true
migration_source: "docs/azents/adr/0141-correlate-terminal-run-events.md"
---

# Correlate Terminal Run Events by Run ID Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `terminal-260712`
- Source: `docs/azents/adr/terminal-260712-terminal-events.md`
- Historical source date basis: `2026-07-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Chat live state can receive terminal control events after a later Run has already become active. Existing `RunComplete`, `RunStopped`, and `live_run_cleared` payloads do not consistently identify the Run they terminate. The frontend can therefore clear the current Run in response to a delayed event from an older Run.

A separate defect allows the session-level unhandled-error reporter to publish `RunComplete` without first transitioning the corresponding AgentRun to a durable terminal state. This makes a stream boundary disagree with the database lifecycle.

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
