---
title: "ADR-0104: Per-Prompt Reasoning Effort Is a Run Boundary"
created: 2026-07-10
tags: [architecture, agent, backend, engine, frontend]
---

# ADR-0104: Per-Prompt Reasoning Effort Is a Run Boundary

## Context

ADR-0103 defines a prompt's selected main model as a FIFO `AgentRun` boundary and preserves the invariant that one run uses one main model. Reasoning-capable models may also expose a finite set of configurable effort levels. Users need to choose an effort together with the model for each prompt.

`RunRequest.reasoning_effort` is currently fixed for the lifetime of an `AgentRun`. Applying a newly queued effort inside the active run would make the effective inference profile vary between model calls even when the main model is unchanged. That would create the same retry, audit, and observability ambiguity that ADR-0103 avoids for model changes.

## Decision

Treat the prompt's requested model target and reasoning effort together as its requested inference profile and FIFO run boundary.

Consecutive pending inputs may share an `AgentRun` only when their requested model targets and reasoning efforts exactly match. Under the current static active-run join policy in ADR-0118, matching input reuses the active run's already resolved profile without re-resolution. If the requested profile differs, the later input remains queued for the next run, where authoritative resolution occurs.

The composer exposes an effort selector only when the selected model snapshot reports reasoning support with selectable effort levels. Reasoning models without selectable effort levels and non-reasoning models do not expose the control and use no explicit per-prompt effort override.

One `AgentRun` uses one main model snapshot and one effective reasoning effort. Runtime does not change either value between model calls in that run.

## Rejected options

### Change effort between model calls in one AgentRun

This would make automatic retry and run-level observability depend on turn-local state and would violate the stable inference-profile boundary chosen for per-prompt model selection.

### Ignore effort changes while the model is unchanged

This would silently discard explicit user intent and make the composer control misleading.

## Consequences

- Input buffering and run segmentation compare the complete inference profile, not only the model snapshot.
- Input, user-message, and AgentRun provenance must include the effective reasoning effort.
- A prompt that changes only effort may wait for the current run to finish.
- UI may validate effort against its current target preview, while run-time resolution remains authoritative and fails explicitly when the resolved model cannot honor the request.
- Session default and persistence behavior follow ADR-0106 and do not change the run-boundary invariant.
