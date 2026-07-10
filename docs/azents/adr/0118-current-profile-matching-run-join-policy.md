---
title: "ADR-0118: Reuse the Active Run Profile for Matching Inputs"
created: 2026-07-10
tags: [architecture, backend, engine, routing]
---

# ADR-0118: Reuse the Active Run Profile for Matching Inputs

## Context

While an AgentRun is active, additional FIFO input can arrive with the same requested target label and reasoning effort. The current target implementation is static, but ADR-0105 intentionally leaves room for a future dynamic router. Re-resolving every matching input during an active run would introduce speculative routing for work that has not started a new run and could produce a physical model different from the active run's immutable profile.

The correct join semantics for a future dynamic router may depend on routing inputs and guarantees that do not exist yet. This feature should not prematurely define those future semantics.

## Decision

For the current per-prompt model-selection implementation, an additional input whose requested target label and reasoning effort exactly match the active AgentRun's requested profile may join that run. It reuses the active run's resolved model snapshot and effective reasoning effort without invoking target resolution again.

An input with a different requested target or effort remains queued for a later AgentRun. Once the active run ends, any subsequent run resolves its requested target again against then-current Agent configuration, even if its requested profile matches the prior run.

Do not pre-resolve a queued input merely to decide whether it can join an active run.

This decision is deliberately limited to the current static target implementation. Introducing dynamic routing must revisit run-join and re-resolution semantics as an explicit design decision rather than treating this ADR as the final dynamic-routing policy.

## Rejected options for the current implementation

### Re-resolve every matching input during the active run

This performs speculative routing, can conflict with the active run's immutable physical model, and provides no stable behavior for a future non-deterministic router.

### Force every user message into a new AgentRun

This removes existing FIFO continuation behavior even when the requested profile is unchanged.

## Consequences

- `_next_flush_prefix` or its replacement segments pending buffers by exact requested target and effort.
- Active-run polling accepts only the matching requested-profile prefix.
- Matching input inherits the active run's resolved profile and receives an association with that AgentRun.
- A different profile remains queued and causes a new run only after the current run becomes terminal.
- Dynamic routing work carries an explicit follow-up design requirement for join and re-resolution behavior.
