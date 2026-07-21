---
title: "Use Handoff Resume Wrapper When Injecting Compaction Summary Historical Requirements Reconstruction"
created: 2026-05-31
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: compaction-260531
historical_reconstruction: true
migration_source: "docs/azents/adr/0044-compaction-summary-injection-wrapper.md"
---

# Use Handoff Resume Wrapper When Injecting Compaction Summary Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `compaction-260531`
- Source: `docs/azents/adr/compaction-260531-compaction-summary-injection-wrapper.md`
- Historical source date basis: `2026-05-31`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[codex-260530/ADR](../adr/codex-260530-codex-compaction-checkpoints.md) decided to generate compaction summaries as Codex-like handoff checkpoints. However, even if the summary generation prompt improves, if the generated summary is injected into the next model input as a raw user message, the next agent can interpret it as ordinary conversation content or as a message to confirm.

Especially when the next user input after compaction is short or test-like, the agent may respond as if it manually verified the summary and end the turn instead of continuing the `Pending Work` in the checkpoint.

Codex's compaction implementation adds a separate prefix before the summary, explicitly saying that another language model started the work, and the current model should continue from the summary while avoiding duplication. Azents needs a wrapper with the same meaning when reinjecting the generated checkpoint into the model.

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
