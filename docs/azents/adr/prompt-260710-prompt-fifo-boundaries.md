---
title: "Per-Prompt Models Form FIFO Run Boundaries"
created: 2026-07-10
tags: [architecture, agent, backend, engine, frontend, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: prompt-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0103-per-prompt-model-fifo-run-boundaries.md"
---

# prompt-260710/ADR: Per-Prompt Models Form FIFO Run Boundaries

## Context

[label-260709/ADR](./label-260709-label-targets.md) introduced Agent-owned label-based model targets partly to support future chat-time model selection. The current execution path resolves one effective main model before an `AgentRun` starts and keeps that model fixed for the full run. At the same time, the input buffer may promote multiple queued human inputs together and may inject newly queued input at later model-call boundaries within the active run.

Adding a model label only to the public message request would therefore not guarantee per-prompt behavior. Inputs that selected different models could be folded into one run whose `RunRequest` contains only one main model. Switching the model inside an active run would instead make retry, compaction, context budgeting, subagent inheritance, and run-level observability depend on turn-local model state.

## Decision

Treat the durable Agent-owned model target label attached to a human prompt as a FIFO execution boundary.

Consecutive pending inputs with the same requested model target may be promoted into the same active or next `AgentRun` according to the active-run join policy. For the current static implementation, an input that exactly matches the active run's requested target and effort joins without target re-resolution under [profile-260710/ADR](./profile-260710-profile-matching-join-policy.md). When the next pending input requests a different target or effort, it is not injected into the current run. It remains queued and starts the next run after the current run boundary completes.

One `AgentRun` continues to use exactly one resolved main model. Target resolution occurs at the run boundary under [time-260710/ADR](./time-260710-time-target-resolution.md); runtime does not switch models between model calls inside that run.

Runs without an explicit requested profile inherit the session's last-used profile under [used-260710/ADR](./used-260710-used-inference-profile.md). A session with no last-used profile starts from the Agent default target.

## Rejected options

### Select a model only when a run starts

This is simpler but does not preserve the model selected by each queued prompt. Multiple inputs with different selections can be flushed into one run, making the request-level choice misleading.

### Switch models between calls inside one AgentRun

This provides immediate turn-local switching but breaks the existing one-run/one-main-model invariant. It would require turn-local retry, compaction, context-budget, audit, and subagent model semantics before the product needs that flexibility.

### Let the latest queued selection win

Latest-wins loses earlier user intent and makes execution depend on enqueue timing rather than FIFO order.

## Consequences

- A prompt submitted with a different model may wait for the active run to finish before execution begins.
- Input-buffer promotion must stop at model-target boundaries and preserve remaining FIFO input for a follow-up wake-up.
- The requested target label must survive input acceptance, event promotion, worker restart, and retry boundaries.
- AgentRun and user-message projections need requested-target and resolved-model provenance for retry, UI display, and observability.
- Run-producing public chat clients submit an explicit profile under [public-260710/ADR](./public-260710-public-inference-profile-request-contract.md); only internal implicit execution uses session/default precedence.
- Internal execution sources without a human composer need an explicit inheritance or default policy in the feature design.

## Migration provenance

- Historical source filename: `0103-per-prompt-model-fifo-run-boundaries.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
