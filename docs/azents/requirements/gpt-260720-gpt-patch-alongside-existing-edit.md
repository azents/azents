---
title: "Add GPT-aligned apply-patch alongside the existing edit tool Historical Requirements Reconstruction"
created: 2026-07-20
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: gpt-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0172-gpt-apply-patch-alongside-existing-edit.md"
---

# Add GPT-aligned apply-patch alongside the existing edit tool Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `gpt-260720`
- Source: `docs/azents/adr/gpt-260720-gpt-patch-alongside-existing-edit.md`
- Historical source date basis: `2026-07-20`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently exposes `edit`, `write`, and `delete_file` as model-visible file
function tools. `edit` replaces one exact string pattern in one UTF-8 file per call. Large
GPT coding edits therefore require repeated tool calls for multiple hunks or files.

OpenAI GPT and Codex models have direct prompting and harness evidence for the V4A patch
format. Claude and Gemini production harnesses instead use exact replacement editors, and
cross-model evidence does not establish V4A as their best editing representation.

Azents will add a GPT-specific `apply_patch` function tool without changing the existing
`edit` contract or introducing provider-hosted, custom, freeform, partially executed, or
stream-preview tool semantics.

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
