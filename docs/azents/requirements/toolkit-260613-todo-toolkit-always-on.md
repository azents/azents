---
title: "Split TodoToolkit as Always-on Toolkit Historical Requirements Reconstruction"
created: 2026-06-13
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: toolkit-260613
historical_reconstruction: true
migration_source: "docs/azents/adr/0059-todo-toolkit-always-on-split.md"
---

# Split TodoToolkit as Always-on Toolkit Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `toolkit-260613`
- Source: `docs/azents/adr/toolkit-260613-todo-toolkit-always-on.md`
- Historical source date basis: `2026-06-13`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[todo-260613/ADR](../adr/todo-260613-todo-toolkit-ui.md) decided to expose session Todo through existing Toolkit State and Chat Live State. Initial implementation placed `update_todo` inside builtin toolkit. However, todo has a different nature from builtin tool bundles such as shell/file/memory. It is not a feature users toggle in Toolkit settings UI; it is session-scoped control state for consistently showing progress of long-running work in every session.

Also, UI requirement is not to show todo as transcript tool card, but as one-line checklist preview attached immediately above input box and as read-only list modal.

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
