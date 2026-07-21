---
title: "Resolve Prompt Model Targets at Run Time"
created: 2026-07-10
tags: [architecture, agent, backend, engine, routing, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: time-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0105-run-time-model-target-resolution.md"
---

# time-260710/ADR: Resolve Prompt Model Targets at Run Time

## Context

[label-260709/ADR](./label-260709-label-targets.md) introduced Agent-owned label-based model targets, and [prompt-260710/ADR](./prompt-260710-prompt-fifo-boundaries.md) made a prompt's requested target a FIFO run boundary. A target can either be resolved to a model snapshot when the server accepts the prompt or remain a durable routing intent until its `AgentRun` starts.

Freezing the current option snapshot at input acceptance makes queued execution deterministic, but it turns the label into an alias that is dereferenced only once. That limits the target abstraction to static model selection and makes it harder to evolve the same contract into dynamic model routing based on current policy, availability, capability, or cost.

Resolving later means Agent target configuration may change while an input is queued. Silent fallback would hide that change and could execute a different model than the requested target contract permits.

## Decision

Persist the requested Agent-owned model target label and reasoning effort with the prompt, but do not freeze an `AgentModelSelection` snapshot at input acceptance.

At each new `AgentRun` boundary, resolve the requested target against the current Agent target configuration. The current static implementation resolves the label to the option's saved `AgentModelSelection`; future routing implementations may resolve the same target through dynamic policy without changing the public prompt contract.

This qualifies [label-260709/ADR](./label-260709-label-targets.md)'s earlier statement that runtime does not resolve labels. Agent model-option inputs are still normalized into saved snapshots when Agent settings are written, and neither the external runtime nor provider adapter reads labels, catalogs, or Workspace defaults. The Azents worker's run-preparation layer now selects an Agent-owned saved target snapshot by label before constructing `RunRequest`.

Target resolution is strict. If the requested label no longer exists, routing cannot produce an eligible model, or the resolved model cannot honor the requested reasoning effort, the run fails explicitly. It must not fall back to the first option, Agent default, another effort, or another model outside the target's routing contract.

After successful resolution, the resulting model snapshot and effective reasoning effort are fixed for that `AgentRun` and recorded as actual execution provenance. Automatic retry inside the same run reuses that resolved profile.

Runs without an explicit target inherit the AgentSession's last-used target under [used-260710/ADR](./used-260710-used-inference-profile.md). The Agent default target is used only when that session has no last-used target. Neither source is a fallback for an explicitly requested or inherited target that fails resolution.

## Rejected options

### Freeze the model snapshot when accepting the prompt

This guarantees enqueue-time determinism but prevents queued prompts from using current target policy and weakens the target label as a future dynamic-routing boundary.

### Resolve at run time with fallback

Fallback keeps execution moving but silently changes user intent and makes routing failures invisible. It also prevents operators and users from distinguishing an unavailable target from a successful policy decision.

### Let the client submit a resolved model snapshot

This bypasses Agent-owned target policy and trusts stale or unauthorized provider/model data from the client.

## Consequences

- InputBuffer and durable user-message state store requested target intent, not a frozen model snapshot.
- Worker run preparation owns authoritative target and effort resolution.
- AgentRun records both the requested target and resolved model profile for audit and UI projection.
- Agent target changes affect prompts that have not started a run yet.
- Missing, invalid, or unsatisfied targets become explicit failed-run errors with actionable user-safe messages.
- Manual retry and edit behavior must define whether they re-resolve the original target or submit a new target intent.
- Dynamic routing can be added behind the target resolver without changing the composer API.

## Migration provenance

- Historical source filename: `0105-run-time-model-target-resolution.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
