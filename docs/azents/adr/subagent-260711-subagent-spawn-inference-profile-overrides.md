---
title: "Allow Explicit Inference Profiles When Spawning Subagents"
created: 2026-07-11
tags: [architecture, agent, backend, engine, subagent, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: subagent-260711
historical_reconstruction: true
migration_source: "docs/azents/adr/0124-subagent-spawn-inference-profile-overrides.md"
---

# subagent-260711/ADR: Allow Explicit Inference Profiles When Spawning Subagents

## Context

[subagent-260710/ADR](./subagent-260710-subagent-parent-profile-inheritance.md) requires a newly spawned subagent to inherit the complete effective inference profile of the concrete parent `AgentRun`. This keeps the child on the same resolved physical model and reasoning effort instead of falling back to Agent defaults or re-resolving the parent's target.

Some delegated tasks benefit from a different Agent-owned model target or reasoning effort. The existing `spawn_agent` contract cannot express that intent. Any extension must preserve parent-run inheritance as the default, use the existing label-based target boundary, respect forked-context continuity, and avoid creating an unusable child when the requested profile is invalid.

Predefined subagent profiles and per-follow-up profile overrides are not part of the current product contract and are outside this decision.

## Decision

Add optional `model_target_label` and `reasoning_effort` fields to `spawn_agent`.

When both fields are omitted, preserve [subagent-260710/ADR](./subagent-260710-subagent-parent-profile-inheritance.md) exactly:

- inherit the parent `AgentRun`'s requested model target label;
- copy the parent run's resolved `AgentModelSelection` snapshot and resolved reasoning effort;
- copy the parent run's effective context window and automatic compaction threshold;
- record `inference_profile_source = parent_run`.

The Agent-level default profile is never consulted for this inheritance path.

When either override field is present, record `inference_profile_source = spawn_override` and derive the child profile as follows:

- An explicit model target is resolved only from the owning Agent's current `selectable_model_options`. Physical provider or model identifiers are not accepted.
- Model-visible tool guidance, schemas, results, and validation errors identify model choices only by Agent-owned target label. They do not reveal provider names, physical model identifiers, model display names, resolved snapshots, or catalog metadata. Supported reasoning-effort values may be associated with a label without exposing the underlying model identity.
- An explicit reasoning effort is validated exactly against the effective model's normalized effort levels. Unsupported explicit effort is rejected rather than normalized silently.
- When only the model target changes, use the parent run's `resolved_reasoning_effort` as the transition baseline and apply the canonical [effort-260710/ADR](./effort-260710-reasoning-effort-in-input.md) normalization rule: preserve the same effort when supported, otherwise choose the greatest supported lower effort, otherwise choose the smallest supported effort. A null baseline uses `medium`. A target with no explicit effort levels produces null.
- When only reasoning effort changes, retain the parent run's resolved model snapshot and validate the requested effort against it.
- The first child run stores the resulting resolved model snapshot, resolved effort, effective limits, and requested profile durably before wake-up publication.

Full-history forks preserve inference continuity. `fork_turns = all`, including the default when `fork_turns` is omitted, rejects any explicit model or effort override. `fork_turns = none` and positive bounded turn counts allow overrides.

Validate the fork/profile combination, target existence, and effort capability before creating the child `SessionAgent`, child `AgentSession`, or pending `AgentRun`. Persist child identity, the precreated first run, the child session's last-used requested profile, and forked context in one transaction. Publish the wake-up only after commit.

The spawn-selected requested label and effort become the child session's last-used profile. Later `followup_task` runs carry no profile override and use normal session-last-used resolution. They are not permanently pinned to the first run's physical model snapshot.

Model-visible guidance follows Codex V2's placement and strength. The dynamic `spawn_agent` description presents parent-Run inheritance as the preferred default and tells the model to set a target label only when an explicit override is needed. It lists Agent-owned labels and their supported effort values without revealing the physical model behind a label. General collaboration prompting is not expanded with a separate model-routing policy, and the stronger Codex V1 requirement for an explicit user request or a stated task-specific reason is not added.

## Rejected options

### Fall back to the Agent default

Agent defaults do not represent the concrete parent run that delegated the task and would silently change the child execution profile.

### Accept or prompt with provider or physical model identifiers

This bypasses the Agent-owned target abstraction and leaks implementation details that labels are intended to hide. Model-visible selection and errors use labels only.

### Add the stronger Codex V1 override authorization prompt

Requiring an explicit user request or a stated task-specific reason is stronger than Codex V2. Azents follows the V2 guidance that inheritance is preferred and a target should be set only when an explicit override is needed.

### Allow overrides for full-history forks

A full-history fork is a continuity boundary. Changing model or effort while preserving the complete parent execution history weakens that boundary and diverges from the Codex policy Azents follows by default.

### Use `explicit_input` provenance

A subagent spawn tool call is not a human Composer input. A distinct `spawn_override` source keeps audit and UI projections unambiguous.

### Pin the first resolved snapshot for the child lifetime

Normal AgentSession behavior persists requested label and effort, then resolves each new run. Permanently pinning a child would introduce a separate session model lifecycle and bypass label-based routing updates.

### Add model and effort fields to `followup_task`

A spawned child is an independent session actor. Follow-up work reuses its session profile. Per-follow-up overrides are a separate feature if a concrete need appears.

## Consequences

- Existing `spawn_agent` calls remain parent-run inheritance calls when they omit the new fields.
- A new inference profile source and corresponding database enum migration are required.
- Spawn tool schema guidance exposes Agent-owned target labels and normalized reasoning efforts without revealing the physical model behind any label.
- Invalid overrides fail the tool call without leaving child identity or run rows behind.
- The first child run remains restart-safe because its resolved profile is durable before broker wake-up.
- Later child runs follow the same session-last-used model target semantics as root sessions.

## Migration provenance

- Historical source filename: `0124-subagent-spawn-inference-profile-overrides.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
