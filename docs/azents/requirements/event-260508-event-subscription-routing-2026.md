---
title: "Slack/Discord/Scheduled Event Subscription Migration Historical Requirements Reconstruction"
created: 2026-05-08
implemented: 2026-05-08
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: event-260508
historical_reconstruction: true
migration_source: "docs/azents/design/event-subscription-routing-2026-05-08.md"
---

# Slack/Discord/Scheduled Event Subscription Migration Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `event-260508`
- Source: `docs/azents/design/event-260508-event-subscription-routing-2026.md`
- Historical source date basis: `2026-05-08`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Migrate Slack, Discord, Scheduled task inputs from “path that directly puts message into specific `AgentSession`” to “path that routes events from external event sources subscribed by agent into active runtime input.”

Core principles:

- Do not recreate adapter-specific session concept per Slack/Discord/Scheduled source.
- Keep `AgentSession` as conversation/event log boundary.
- Event subscription is responsible only up to input routing.
- External posting (output) is handled by agent explicitly calling output tool target, not by implicit reply adapter.

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
