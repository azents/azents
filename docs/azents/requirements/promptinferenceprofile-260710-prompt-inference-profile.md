---
title: "Per-Prompt Inference Profile Historical Requirements Reconstruction"
created: 2026-07-10
implemented: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: promptinferenceprofile-260710
historical_reconstruction: true
migration_source: "docs/azents/design/per-prompt-inference-profile.md"
---

# Per-Prompt Inference Profile Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `promptinferenceprofile-260710`
- Source: `docs/azents/design/promptinferenceprofile-260710-prompt-inference-profile.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently resolves every normal Agent run from the Agent's denormalized main `model_selection` and Agent-level reasoning effort. The chat Composer cannot choose a different Agent-owned model target for one prompt. Pending inputs are also flushed as one prefix before an action barrier, so adding fields only to the REST request would not preserve prompt-specific execution intent.

The feature must let a user choose Model and optional reasoning effort for each prompt while preserving these runtime invariants:

- one main physical model and one effective effort per `AgentRun`;
- FIFO input ordering;
- strict Agent-owned target policy rather than client-submitted provider snapshots;
- stable automatic retry within a run;
- durable requested and resolved provenance;
- exact parent-run profile inheritance for the first subagent run.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Add a compact per-prompt Model and effort selector to chat.
- Treat target label and effort as one requested inference profile and FIFO run boundary.
- Resolve labels authoritatively at each new run against current Agent target configuration.
- Preserve a fixed resolved profile throughout one run and its automatic retries.
- Persist the latest successfully activated profile on AgentSession for implicit execution.
- Preserve profile intent through queueing, reload, edit, and manual retry.
- Make requested target and actual resolution inspectable from the originating user message.
- Keep context/token usage tied to actual run provenance.
- Give a new subagent the exact resolved parent-run profile for its first run.

## Non-goals

- Dynamic model routing policy. The current implementation resolves a label to its saved static `AgentModelSelection` snapshot.
- Final dynamic-routing semantics for inputs arriving during an active run.
- A `spawn_agent` model or effort override.
- Per-prompt lightweight/compaction model selection.
- Voice input or unrelated Composer actions.
- Letting clients submit provider IDs, physical model snapshots, credentials, or routing results.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
