---
title: "Adopt Event / Native Event Terminology Historical Requirements Reconstruction"
created: 2026-06-13
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: event-260613
historical_reconstruction: true
migration_source: "docs/azents/adr/0057-event-native-event-terminology.md"
---

# Adopt Event / Native Event Terminology Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `event-260613`
- Source: `docs/azents/adr/event-260613-event-event-terminology.md`
- Historical source date basis: `2026-06-13`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The durable event model of Azents runtime transcript is not a "canonical event" with a separate opposite concept. It is the normal event inside the system. Keeping the `canonical` prefix or package to distinguish it blurs the boundary between durable transcript event and lower target event.

On the other hand, an event lowered into model/provider adapter is no longer an Azents event, but a target-native event. Provider- or adapter-specific native representations such as LiteLLM Responses, OpenAI Responses, and Claude Messages should each have explicit names.

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
