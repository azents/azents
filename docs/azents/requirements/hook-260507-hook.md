---
title: "Runtime Hook System Historical Requirements Reconstruction"
created: 2026-05-07
implemented: 2026-05-07
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: hook-260507
historical_reconstruction: true
migration_source: "docs/azents/design/runtime-hook-system.md"
---

# Runtime Hook System Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `hook-260507`
- Source: `docs/azents/design/hook-260507-hook.md`
- Historical source date basis: `2026-05-07`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Unknown — the historical source does not state this explicitly.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Provide a simple model where hook authors explicitly register only lifecycle callbacks they support in `Toolkit.hooks()`.
- Keep current `Toolkit` as provider boundary while recording that it may be renamed to runtime capability provider long term.
- Define first taxonomy and callback semantics for session, run, turn, tool, and sandbox lifecycles.
- Provide small lifecycle-specific result types, while observation-only hooks return `None`.
- Allow only approved minimal mutations: tool deny, tool output text replacement, and turn start prompt injection.
- Keep prompt assembly ownership in existing `update_context()` and `ToolkitState.prompt`.
- Specify active provider order, failure policy, and trace policy as runner contract.
- Make hook trace useful for tests and operations diagnostics without storing raw args/output/prompt/credentials.

## Non-goals

- This document does not include phase plan, per-file implementation checklist, or PR split plan.
- Renaming `Toolkit` or introducing a separate provider base class is out of scope.
- Do not introduce external arbitrary plugin runtime, plugin manifest, plugin sandbox, or third-party hook execution.
- Model lifecycle hook is excluded from first implementation. `on_before_model_call` and `on_after_model_call` are not defined.
- Memory, external event, and attachment lifecycle are excluded from this taxonomy.
- Do not introduce `PromptBlock` or `ContextBlock` abstraction.
- Do not provide universal `HookResult`, arbitrary mutation, continuation, or retry wrapper model.
- Do not provide an API for hook authors to directly create durable audit events.
- Durable DB audit or OTel export is not required in initial implementation.

## Requirements

- baseline provider registering no hooks
- turn prompt injection provider
- before tool deny provider
- before/after exception provider
- after output replacement provider, two or more
- deterministic scenarios inducing run/turn end reason normal/error/cancel/unknown

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
