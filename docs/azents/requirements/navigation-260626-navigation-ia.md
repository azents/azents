---
title: "Agent-Focused Navigation Information Architecture Historical Requirements Reconstruction"
created: 2026-06-26
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: navigation-260626
historical_reconstruction: true
migration_source: "docs/azents/adr/0078-agent-focused-navigation-ia.md"
---

# Agent-Focused Navigation Information Architecture Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `navigation-260626`
- Source: `docs/azents/adr/navigation-260626-navigation-ia.md`
- Historical source date basis: `2026-06-26`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

The Agent detail UI uses an Agent-focused shell with its own sidebar/drawer and Agent header. On
mobile, the global app bar plus the Agent header consume too much vertical space for chat. The Agent
sidebar also duplicated Agent section navigation (`Chat`, `Context`, `Settings`) that already belongs
to the Agent header/tab area. This duplication pushed the session list down and made it unclear which
navigation surface owned Agent section switching.

The workspace sidebar and Agent-focused sidebar should also feel like one product. Users move from the
workspace sidebar into an Agent-specific sidebar, so menu naming, grouping, and responsibilities should
stay consistent instead of changing meaning between screens.

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
