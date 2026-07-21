---
title: "Render Known Tools Through Validated Frontend Adapters Historical Requirements Reconstruction"
created: 2026-07-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: known-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0176-render-known-tools-through-validated-frontend-adapters.md"
---

# Render Known Tools Through Validated Frontend Adapters Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `known-260720`
- Source: `docs/azents/adr/known-260720-known-tools-through-validated-frontend-adapters.md`
- Historical source date basis: `2026-07-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[group-260720/ADR](../adr/group-260720-group-chat-activity-in-the-frontend.md) established Generic tool rendering as the permanent compatibility boundary and allowed specialized presentation only for registered tool identities whose payloads validate. [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-194) retained that boundary while deferring individual tool detail designs.

The current web implementation still renders every client tool through `ToolCallCard` and every provider-hosted tool through `ProviderToolCallCard`. These components expose raw arguments, raw textual output, status, and attachments, but they cannot communicate common operations such as file reads, searches, edits, shell commands, memory actions, or subagent lifecycle in a concise product-level form.

This follow-up must add useful known-tool presentation without making chat rendering depend on mutable Toolkit configuration, arbitrary tool-name prefixes, unvalidated JSON, or backend-owned UI payloads. Unknown, historical, malformed, and newly introduced tools must remain fully inspectable.

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
