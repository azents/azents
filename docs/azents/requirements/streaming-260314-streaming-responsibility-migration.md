---
title: "Streaming Responsibility Migration — From Handler to Worker Historical Requirements Reconstruction"
created: 2026-03-14
implemented: 2026-03-23
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: streaming-260314
historical_reconstruction: true
migration_source: "docs/azents/design/streaming-responsibility-migration.md"
---

# Streaming Responsibility Migration — From Handler to Worker Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `streaming-260314`
- Source: `docs/azents/design/streaming-260314-streaming-responsibility-migration.md`
- Historical source date basis: `2026-03-14`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Currently Slack/Discord handlers each create streaming task, subscribe to Broker Redis Pub/Sub, and deliver responses. When messages arrive sequentially for same session, **duplicate subscribers are created** and **messages are sent multiple times** to Slack/Discord.

This document describes design that structurally solves the problem by migrating streaming responsibility from Handler to Worker.

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
