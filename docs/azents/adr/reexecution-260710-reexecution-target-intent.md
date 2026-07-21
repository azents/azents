---
title: "Re-Execution Preserves Model Target Intent"
created: 2026-07-10
tags: [architecture, agent, backend, chat, engine, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: reexecution-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0107-reexecution-model-target-intent.md"
---

# reexecution-260710/ADR: Re-Execution Preserves Model Target Intent

## Context

Message editing and failed-run recovery create new execution boundaries after an earlier prompt already carried a requested model target and reasoning effort. The new run could inherit the session's latest profile, reuse the earlier run's resolved model snapshot, or preserve the original requested target intent and resolve it again.

Reusing the session profile can silently change the edited or retried prompt's model. Reusing a resolved snapshot preserves the prior physical model but bypasses the current target policy and the dynamic-routing boundary established by [time-260710/ADR](./time-260710-time-target-resolution.md).

Automatic provider/run retry is different: it occurs inside the same `AgentRun`, where model and effort are already fixed.

## Decision

Message editing and manual failed-run retry preserve the original prompt's requested model target label and reasoning effort by default.

The edit UI initializes its model and effort controls from the edited user message's requested profile. The user may explicitly change either value as part of the edit request. When unchanged, the new edited input carries the original requested profile.

Manual failed-run retry carries the failed run's original requested target and effort into a new `AgentRun`. The new run resolves that target against current Agent routing configuration under [time-260710/ADR](./time-260710-time-target-resolution.md); it does not reuse the failed run's resolved model snapshot.

Automatic retry inside an existing `AgentRun` reuses that run's already resolved model snapshot and effort because it is not a new FIFO run boundary.

## Rejected options

### Use the AgentSession last-used profile

This can replace the original prompt's explicit intent with a later session choice unrelated to the edited or retried request.

### Reuse the original resolved model snapshot

This makes manual retry deterministic at the physical-model level but bypasses current target routing policy and prevents dynamic routing from recovering through a newly eligible model.

### Always use the Agent default

This discards both the original request and session context.

## Consequences

- Durable user-message and failed-run provenance must retain requested target and effort.
- Edit requests accept an explicit requested profile and default the controls from the original message.
- Manual retry can fail if the original target no longer resolves; it does not fall back.
- Routing changes may cause manual retry to use a different physical model while preserving the same logical target.
- Automatic and manual retry intentionally have different resolution timing because only manual retry creates a new AgentRun.

## Migration provenance

- Historical source filename: `0107-reexecution-model-target-intent.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
