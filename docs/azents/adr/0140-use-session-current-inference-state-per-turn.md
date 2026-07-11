---
title: "ADR-0140: Use Session Current Inference State Per Turn"
created: 2026-07-12
tags: [architecture, agent, backend, database, engine, inference]
---

# ADR-0140: Use Session Current Inference State Per Turn

## Context

Earlier inference-profile ADRs bind one requested and resolved model profile to an entire AgentRun. That boundary requires pending inputs with another model to end the current run or wait for a later run. The sequential preparation design instead resolves each model-bearing input before the next turn and stores the final applied configuration on the session.

An AgentRun may contain multiple turns. There is no product requirement that every turn in one AgentRun use the same model, and actual provider/model provenance is internal execution data rather than a chat UI contract.

## Decision

Remove the one-AgentRun/one-resolved-model constraint. Different turns inside the same AgentRun may use different resolved model selections.

Each model-bearing input processor resolves its override during preparation and atomically updates the AgentSession's current resolved inference state. After the queue is empty and TurnEffect permits execution, the next turn reads that already-resolved Session state directly. SessionRunner does not convert a model target label to a model entity and does not require a new AgentRun merely because the resolved model changed.

Use the domain name `SessionInferenceState` for this current prepared configuration. Replace the existing last-used/request-oriented Session fields with current-state fields:

- `current_model_target_label`;
- `current_model_selection`;
- `current_reasoning_effort`;
- `current_effective_context_window_tokens`;
- `current_effective_auto_compaction_threshold_tokens`;
- `current_inference_resolved_at`.

A new Session may keep the state absent until the first model-bearing preparation resolves the Agent default or explicit override. Once present, the state is complete; reasoning effort remains nullable when provider/model default is intentional.

Rename the immutable message-level configuration from `requested_inference_profile` to `applied_inference_profile`. Its internal representation records the target, resolved selection, and effort applied by that message. Public chat projection may expose only the user-relevant target label and effort. It does not expose physical provider/model execution provenance.

Remove run-level requested/resolved inference fields and inference-profile source as authoritative execution configuration. AgentRun remains the multi-turn execution lifecycle and ownership boundary for status, parentage, retry lifecycle, terminal result, and run indexing, but not for model selection.

Actual provider/model execution identity remains internal. Model-produced durable events already carry adapter/provider/model identity where required, and an in-flight turn uses the Session inference snapshot captured at its boundary. Pending input does not mutate Session inference state until the next between-turn preparation boundary, so automatic retry of the current turn continues with the same captured configuration.

Subagent spawn initializes the child Session inference state from the parent turn's current resolved state or a resolved spawn override. It does not pre-bind the child AgentRun to that model.

This decision supersedes the one-run/one-model and run-time-resolution parts of ADR-0103, ADR-0105, ADR-0121, and ADR-0124. Those records remain historical rationale for the previous implementation.

## Rejected Alternatives

### End the current AgentRun whenever the model changes

This preserves run-level provenance but turns a model selector change into an internal run lifecycle boundary with no product meaning and complicates continuous multi-turn execution.

### Delay the new model until the current AgentRun ends

The prepared Session state would not control the next turn, contradicting sequential buffer preparation and the user's applied override.

### Keep duplicate Session and AgentRun inference snapshots

Two authoritative configurations can diverge during turn transitions and require synchronization logic solely to preserve the old boundary.

## Consequences

- One AgentRun may execute turns through different providers or models.
- Model resolution moves fully into input/edit/spawn preparation.
- SessionRunner consumes `SessionInferenceState` and no longer routes target labels.
- AgentRun schemas, repositories, APIs, live projections, and retry logic lose run-bound inference fields.
- User-message history stores immutable applied configuration without later AgentRun joins or mutation.
- UI does not need actual physical model identity for a response.
- Compaction and context budgeting use the Session inference snapshot captured for the current turn.
- Tests must cover model changes between turns in one AgentRun and retry stability within one turn.

## References

- [ADR-0103: Per-Prompt Models Form FIFO Run Boundaries](./0103-per-prompt-model-fifo-run-boundaries.md)
- [ADR-0105: Resolve Prompt Model Targets at Run Time](./0105-run-time-model-target-resolution.md)
- [ADR-0121: Atomically Activate the Resolved Run and Session Profile](./0121-atomic-run-profile-activation.md)
- [ADR-0124: Keep Inference Provenance Run-Owned](./0124-keep-inference-provenance-run-owned.md)
- [ADR-0126: Resolve User Message Profiles During Buffer Preparation](./0126-resolve-user-message-profile-during-buffer-preparation.md)
