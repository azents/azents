---
title: "Group Chat Tool Activity in the Frontend Historical Requirements Reconstruction"
created: 2026-07-20
implemented: 2026-07-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: group-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0173-group-chat-tool-activity-in-the-frontend.md"
---

# Group Chat Tool Activity in the Frontend Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `group-260720`
- Source: `docs/azents/adr/group-260720-group-chat-activity-in-the-frontend.md`
- Historical source date basis: `2026-07-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently projects client and provider tool calls into individual chat cards. This preserves diagnostic detail, but a long-running Agent may produce many cards across several model turns before it sends another user-visible response. The repeated cards, status badges, arguments, outputs, and attachments dominate the timeline and make the assistant's actual communication harder to scan.

The canonical event and frontend projection models already expose stable tool identity, name, status, arguments, output, and attachments through `call_id`, `ActiveToolCall`, and `ProviderToolCall`. Changing backend tool payloads solely to support a calmer presentation would couple the event contract to one UI composition and duplicate information that the frontend already has.

The product requires multi-turn grouping when tool execution continues without visible assistant communication, progressive disclosure for details, specialized presentation only for payload shapes the frontend understands, and a safe generic fallback for every other shape.

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
